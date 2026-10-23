/* The Quant Ace — core: namespace, state, routing, cached loading, helpers, search, and the shell from
 * The Quant design kit (assets/qk: QK.shell top bar, the section nav, search palette, theme; charts
 * through the kit's QKC on ECharts).
 *
 * Sections (docs/REDESIGN.md; tennis labels): Overview #/<T> · Draws (tournaments, draws and draw
 * simulations, match centre, odds board) · Rankings (rankings, race, Elo) · Players (players, player
 * pages, head to head) · Value (breakouts, luck, over- and undervalued) · Lab (scatter lab, compare) ·
 * Model (methodology, calibration, glossary, terms). Tennis has no Teams and no Fantasy. Every old
 * route still resolves.
 *
 * A static shell over JSON payloads under data/ (see oddsmarkets/tennis/PAYLOADS.md).
 * Every page module registers itself with TA.route(name, renderFn) and never edits this
 * file. Routes (hash) carry the tour first; T is 'atp' or 'wta':
 *
 *   #/                              hub (tour = last viewed, default atp)
 *   #/<T>                           hub
 *   #/<T>/event/<event_id>          event (tournament page; event_id = "<tid>-<year>")
 *   #/<T>/match/<mid>               match centre
 *   #/<T>/player/<pid>              player
 *   #/<T>/players  rankings  race  elo  calendar  lab  markets  calibration  value (?v=breakout|luck|over|surface|market|validation)
 *   #/<T>/h2h[/<a>[/<b>]]           head to head
 *   #/<T>/compare[/<a>[/<b>]]       compare players
 *   #/glossary[/<key>]  #/methodology  #/disclaimer   (global; a tour prefix is accepted)
 *
 * Year: every page reads the year from TA.state.year. It comes from a "?y=<YYYY>" query
 * (any page), else the year inside an event or match id, else the tour's current year
 * (index.json tours[T].year). Links built with the helpers below carry ?y= when the year
 * shown is not the current one.
 *
 * Before a page renders, core loads <T>/players_index.json (names for every pid) and
 * <T>/<Y>/events.json (event names), so TA.playerName / TA.eventName work synchronously.
 *
 * A render function is called as fn(el, params, state): `el` is a fresh <div> inside
 * <main id="app"> (detached when the viewer navigates away, so async code can test
 * el.isConnected); `params` holds {tour, year, id, a, b, rest, query}. It may return a Promise.
 *
 * Most helpers take the tour first: playerLink(T, pid). When the first argument is not
 * 'atp'/'wta' it is treated as the id and the current tour is used: playerLink(pid).
 */
window.TA = (function () {
'use strict';

// ── constants ──────────────────────────────────────────────────────────────

/* Colours are design tokens (CSS custom properties): HTML uses them directly, the chart shim resolves them for the
 * current theme at paint time. Player 1 / the model = chart slot 1 (blue), player 2 / the market = slot 2 (orange).
 * Surfaces keep their identity colours (hard blue, clay terracotta, grass green, indoor violet). */
const C = {
  bg: 'var(--bg)', bg2: 'var(--s-1)', bg3: 'var(--s-2)', border: 'var(--line-2)',
  text: 'var(--ink-1)', text2: 'var(--ink-2)', text3: 'var(--ink-3)',
  blue: 'var(--c-1)', green: 'var(--up)', red: 'var(--down)', orange: 'var(--c-2)',
  purple: 'var(--c-7)', yellow: 'var(--c-4)', teal: 'var(--c-3)', ace: 'var(--c-1)', ace2: 'var(--c-1)', accent: 'var(--accent)',
  p1: 'var(--c-1)', p2: 'var(--c-2)',
  hard: '#3b82f6', clay: '#d2693c', grass: '#3fb950', indoor: '#a371f7', carpet: '#8b949e'
};
const PALETTE = ['var(--c-1)', 'var(--c-2)', 'var(--c-3)', 'var(--c-4)', 'var(--c-5)', 'var(--c-6)', 'var(--c-7)', 'var(--c-8)'];
/* A colour at alpha a: hex -> rgba(); a token or any CSS colour -> color-mix(). */
function alpha(c, a) {
  const h = String(c || '').replace('#', '');
  if (/^[0-9a-f]{6}$/i.test(h)) return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
  return 'color-mix(in srgb, ' + (c || 'var(--ink-3)') + ' ' + Math.round(a * 100) + '%, transparent)';
}
const FOOTBALL_URL = 'https://pchattani.github.io/the-quant-footballer/';
const PADDOCK_URL = 'https://pchattani.github.io/the-quant-paddock/';
const HARDWOOD_URL = 'https://pchattani.github.io/the-quant-hardwood/';
const BULLPEN_URL = 'https://pchattani.github.io/the-quant-bullpen/';
const GRIDIRON_URL = 'https://pchattani.github.io/the-quant-gridiron/';
const RINK_URL = 'https://pchattani.github.io/the-quant-rink/';
const TOURS = ['atp', 'wta'];
const TOUR_NAME = { atp: 'ATP', wta: 'WTA' };
const LS_TOUR = 'qa-tour';

const SURFACES = ['hard', 'clay', 'grass'];
const SURFACE_LABEL = { hard: 'Hard', clay: 'Clay', grass: 'Grass', carpet: 'Carpet', indoor: 'Indoor hard', all: 'All surfaces' };
const LEVELS = ['slam', 'finals', 'm1000', '500', '250', 'other', 'ch', 'q'];
const ROUND_ORDER = ['Q1', 'Q2', 'Q3', 'R128', 'R64', 'R32', 'R16', 'RR', 'QF', 'SF', 'BR', 'F'];
const MAIN_ROUNDS = ['R128', 'R64', 'R32', 'R16', 'QF', 'SF', 'F'];
const ROUND_LONG = { Q1: 'Qualifying 1', Q2: 'Qualifying 2', Q3: 'Qualifying 3', R128: 'Round of 128', R64: 'Round of 64', R32: 'Round of 32',
  R16: 'Round of 16', RR: 'Round robin', QF: 'Quarter-final', SF: 'Semi-final', BR: 'Bronze medal match', F: 'Final', W: 'Title' };
const ROUND_SHORT = { Q1: 'Q1', Q2: 'Q2', Q3: 'Q3', R128: 'R128', R64: 'R64', R32: 'R32', R16: 'R16', RR: 'RR', QF: 'QF', SF: 'SF', BR: 'Bronze', F: 'F', W: 'W' };

// ── state and registries ───────────────────────────────────────────────────

const state = { tour: 'atp', year: null, route: null, params: {}, hash: '' };
const INDEX = { data: null };
const NAMES = { atp: {}, wta: {} };          // pid -> {name, short, country, rank}
const EVENTS = { atp: {}, wta: {} };         // year -> {event_id: {...}} (events.json)
const CACHE = {}, PENDING = {};
const HANDLERS = {};
let CLEANUPS = [];

try { const t = window.localStorage.getItem(LS_TOUR); if (TOURS.indexOf(t) >= 0) state.tour = t; } catch (e) { /* private mode */ }

function isTour(x) { return TOURS.indexOf(String(x)) >= 0; }

const ROUTES = [];
function addRoute(pattern, name, fallbacks, defaults, global) {
  ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, fallbacks: fallbacks || [], defaults: defaults || {}, global: !!global });
}
addRoute('', 'hub');
addRoute('event/:id', 'event');
addRoute('match/:id', 'match');
addRoute('player/:id', 'player');
addRoute('players', 'players');
addRoute('rankings', 'rankings');
addRoute('race', 'race');
addRoute('elo', 'elo');
addRoute('calendar', 'calendar');
addRoute('h2h', 'h2h');
addRoute('h2h/:a', 'h2h');
addRoute('h2h/:a/:b', 'h2h');
addRoute('lab', 'lab');
addRoute('compare', 'compare');
addRoute('compare/:a', 'compare');
addRoute('compare/:a/:b', 'compare');
addRoute('markets', 'markets');
addRoute('calibration', 'calibration');
addRoute('value', 'value');
addRoute('glossary', 'glossary', [], {}, true);
addRoute('glossary/:id', 'glossary', [], {}, true);
addRoute('methodology', 'methodology', [], {}, true);
addRoute('disclaimer', 'disclaimer', [], {}, true);

const ALIASES = {
  home: 'hub', index: 'hub', '': 'hub', tour: 'hub', overview: 'hub',
  tournament: 'event', events: 'calendar', schedule: 'calendar', docs: 'methodology', 'head-to-head': 'h2h',
  draws: 'calendar', fixtures: 'calendar', tournaments: 'calendar', standings: 'rankings', model: 'methodology', odds: 'markets', terms: 'disclaimer'
};
const TITLES = {
  hub: 'Overview', event: 'Tournament', match: 'Match centre', player: 'Player', players: 'Players', rankings: 'Rankings',
  race: 'Race', elo: 'Elo', calendar: 'Calendar', h2h: 'Head to head', lab: 'Lab', compare: 'Compare',
  markets: 'Forecasts', calibration: 'Calibration', value: 'Value', glossary: 'Glossary', methodology: 'Methodology', disclaimer: 'Disclaimer & terms'
};
const NAV_OF = { hub: 'hub', event: 'calendar', calendar: 'calendar', match: 'hub', player: 'players', players: 'players',
  rankings: 'rankings', race: 'race', elo: 'elo', h2h: 'h2h', lab: 'lab', compare: 'compare', markets: 'markets',
  calibration: 'calibration', value: 'value', glossary: 'glossary', methodology: 'methodology' };
/* The sections (QK.sections('tennis')) and the routes each one holds. */
const SECTION_OF = { hub: 'overview', calendar: 'fixtures', event: 'fixtures', match: 'fixtures', markets: 'fixtures', rankings: 'standings', race: 'standings',
  elo: 'standings', players: 'players', player: 'players', h2h: 'players', value: 'value', lab: 'lab', compare: 'lab', methodology: 'model',
  calibration: 'model', glossary: 'model', disclaimer: 'model' };
/* Tabs per section: [route, label, scope] with scope 'g' (a global route) or '' (per tour). */
const SECTION_TABS = {
  fixtures: [['calendar', 'Tournaments', ''], ['markets', 'Forecasts', '']],
  standings: [['rankings', 'Rankings', ''], ['race', 'Race to the Finals', ''], ['elo', 'Elo ratings', '']],
  players: [['players', 'All players', ''], ['h2h', 'Head to head', '']],
  value: [['value', 'Player value', '']],
  lab: [['lab', 'Scatter lab', ''], ['compare', 'Compare', '']],
  model: [['methodology', 'Methodology', 'g'], ['calibration', 'Calibration', ''], ['glossary', 'Glossary', 'g'], ['disclaimer', 'Terms', 'g']]
};
const SECTION_LABEL = { overview: 'Overview', fixtures: 'Draws', standings: 'Rankings', players: 'Players', value: 'Value', lab: 'Lab', model: 'Model' };
const SECTION_BLURB = {
  fixtures: 'Every tournament with its draw, our title chances from simulating the rest of it, and our win chance for every match.',
  standings: 'The official rankings, the race to the year-end Finals with our chance of qualifying, and our surface Elo ratings.',
  players: 'Serve and return ratings, surface Elo, form and results for every player, ranked against their tour, and any two head to head.',
  value: 'Who is breaking out, who has been lucky, and whose ranking runs ahead of or behind their level.',
  lab: 'Build your own charts from any two metrics, and put two or three players side by side on the metrics that predict.',
  model: 'How the models work, how well they have done, and every metric defined.'
};
/* v2 page heads: route -> [title, sub-line] (the section blurb when the sub-line is empty). */
const PAGE_HEAD = {
  calendar: ['Tournaments', 'Every tournament of the year with its level, surface and champion; open one for the draw and our title chances.'],
  markets: ['Forecasts', 'Our win chance for every open match and our title chance in every tournament in play, from the same models as the match centre.'],
  rankings: ['Rankings', 'The official ranking points, beside our Elo for every player.'],
  race: ['Race to the Finals', 'Points in this year’s race and our chance of qualifying, from simulating the rest of the season.'],
  elo: ['Elo ratings', 'Our strength ratings from every tour-level result, overall and by surface.'],
  players: ['Players', ''], h2h: ['Head to head', 'Any two players: their record, how they match up on each surface and our chance if they met today.'],
  value: ['Player value', 'Who is likely to rise or fall over the next year, how much of a record is luck, and whose ranking runs ahead of or behind our rating.'], lab: ['Scatter lab', 'Any two metrics for any group of players.'],
  compare: ['Compare', 'Pick two or three players: they line up on the metrics that best describe and predict their tennis, ranked against their own tour.'],
  methodology: ['How the models work', 'The ratings, the match model, the simulations and how well each has done.'],
  calibration: ['Calibration', 'How often our chances came true, and how they compare with the closing market as a reference.'],
  glossary: ['Glossary', 'Every metric on the site, defined.'], disclaimer: ['Disclaimer and terms', '']
};
const DETAIL_OF = { event: 'calendar', match: 'calendar', player: 'players' };
// Where a page lands when the tour is switched (id pages fall back to their list).
const SWITCH_TO = { event: 'calendar', match: 'hub', player: 'players', h2h: 'h2h', compare: 'compare' };

function normPattern(s) {
  let p = String(s || '').trim().replace(/^#/, '').replace(/^\/+|\/+$/g, '').replace(/<(\w+)>/g, ':$1');
  p = p.replace(/^(:T|:tour|atp|wta)(\/|$)/, '');
  return p;
}
function shape(p) { return p.split('/').map(s => (s.charAt(0) === ':' ? ':' : s)).join('/'); }

/* Register a page renderer: a route name ('event'), an alias, or a pattern ('#/<T>/event/<id>'). */
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

/* The year inside an event id ("wimbledon-2026") or a match id ("wimbledon-2026-QF-..."), else null. */
function yearOfId(id) {
  const m = /-((?:19|20)\d\d)(?:-|$)/.exec(String(id || ''));
  return m ? Number(m[1]) : null;
}

function parseHash(hash) {
  let h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  let query = {};
  const qi = h.indexOf('?');
  if (qi >= 0) { query = parseQuery(h.slice(qi + 1)); h = h.slice(0, qi); }
  let parts = h.split('/').filter(s => s !== '').map(s => { try { return decodeURIComponent(s); } catch (e) { return s; } });
  let tour = null;
  if (parts.length && isTour(parts[0].toLowerCase())) { tour = parts[0].toLowerCase(); parts = parts.slice(1); }
  let best = null, bestLen = -1;
  ROUTES.forEach(r => {
    if (r.segs.length > parts.length) return;
    if (r.segs.length === 0 && parts.length > 0) return;
    for (let i = 0; i < r.segs.length; i++) if (r.segs[i].charAt(0) !== ':' && r.segs[i] !== parts[i]) return;
    const score = r.segs.length * 2 + (r.segs.length === parts.length ? 1 : 0);
    if (score > bestLen) { best = r; bestLen = score; }
  });
  const params = { tour: tour, rest: [], query: query };
  if (!best) return { name: 'notfound', params: Object.assign(params, { rest: parts }), parts: parts, tour: tour };
  Object.keys(best.defaults).forEach(k => { params[k] = best.defaults[k]; });
  best.segs.forEach((s, i) => { if (s.charAt(0) === ':') params[s.slice(1)] = parts[i]; });
  params.rest = parts.slice(best.segs.length);
  let y = query.y ? parseInt(query.y, 10) : NaN;
  if (isNaN(y) && (best.name === 'event' || best.name === 'match')) y = yearOfId(params.id) || NaN;
  params.year = isNaN(y) ? undefined : y;
  return { name: best.name, params: params, parts: parts, tour: tour, global: best.global };
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
function render() {
  runCleanups();
  closeSearch();
  const r = parseHash();
  const prevTour = state.tour, prevYear = state.year;
  if (r.tour) setTourState(r.tour);
  r.params.tour = state.tour;
  const Y = r.params.year || currentYear(state.tour);
  r.params.year = Y;
  state.year = Y;
  state.route = r.name;
  state.params = r.params;
  state.hash = location.hash || '#/';
  if (prevTour !== state.tour || prevYear !== state.year || !pickerFilled) fillYearPicker();
  updateHeader();
  markNav(SECTION_OF[r.name] || '');
  const app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '';
  app.appendChild(sectionBar(r));
  const el = document.createElement('div');
  el.className = 'page page-' + r.name.replace(/[^a-z0-9-]/gi, '-') + ' tour-' + state.tour;
  app.appendChild(el);
  document.title = (r.name === 'hub' ? TOUR_NAME[state.tour] + ' ' + (state.year || '') + ' · ' : (TITLES[r.name] || 'Page') + (r.global ? '' : ' · ' + TOUR_NAME[state.tour]) + ' · ') + 'The Quant Ace';
  setMeta('');
  window.scrollTo(0, 0);
  const fn = handlerFor(r.name);
  if (!fn) {
    el.innerHTML = r.name === 'notfound'
      ? comingHTML('Page not found', 'There is no page at <code>' + esc(location.hash) + '</code>. Try the overview or the search (press /).')
      : comingHTML((TITLES[r.name] || 'This page') + ' is coming', 'This part of The Quant Ace is still being built.');
    return;
  }
  const seq = ++renderSeq;
  el.innerHTML = window.QK ? QK.skeleton('lines', 6) : '<div class="muted">Loading…</div>';
  ensureTour(state.tour, Y).then(() => {
    if (seq !== renderSeq || !el.isConnected) return;
    el.innerHTML = '';
    try {
      const out = fn(el, r.params, state);
      if (out && typeof out.then === 'function') out.then(() => jumpNav(el, r), err => showError(el, err));
      else jumpNav(el, r);
    } catch (err) { showError(el, err); }
  });
}

function comingHTML(title, body) {
  return '<div class="qk-card coming"><div class="qk-card-body"><div class="coming-title">' + esc(title) + '</div>' +
    '<p class="muted-inline">' + body + '</p><p><a class="qk-link" href="#/' + state.tour + '">Back to the overview</a></p></div></div>';
}
function tabHref(t, T, Y) { return t[2] === 'g' ? '#/' + t[0] : href(T, t[0], Y); }
/* The bar above every page: section kicker and title, the section's tabs; on a detail page a link back to its list. */
function sectionBar(r) {
  const sec = SECTION_OF[r.name] || '';
  const bar = document.createElement('div');
  bar.className = 'ta-secbar';
  if (!sec || sec === 'overview' || r.name === 'notfound') { bar.hidden = true; bar.innerHTML = '<span id="meta-line" hidden></span>'; return bar; }
  const T = state.tour, Y = state.year;
  const tabs = SECTION_TABS[sec] || [];
  const detail = DETAIL_OF[r.name];
  const glob = (routeEntry(r.name) || {}).global;
  const kicker = glob ? 'The Quant Ace · ATP and WTA' : (tourInfo(T).name || TOUR_NAME[T]) + ' · ' + Y;
  let back = '';
  if (detail) {
    const t = tabs.find(x => x[0] === detail) || [detail, TITLES[detail] || titleCase(detail), ''];
    back = '<a class="ta-back" href="' + tabHref(t, T, Y) + '"><span aria-hidden="true">←</span> ' + esc(SECTION_LABEL[sec] + ' · ' + t[1]) + '</a>';
  }
  bar.classList.toggle('is-detail', !!detail);
  const ph = PAGE_HEAD[r.name] || [SECTION_LABEL[sec], ''];
  bar.innerHTML = (detail ? '<div class="ta-secbar-in"><div class="ta-sec-title"><div class="qk-kicker">' + esc(kicker) + '</div>' + back + '</div><div class="ta-meta" id="meta-line"></div></div>'
    : (window.QK && QK.sectionHead ? QK.sectionHead({ kicker: kicker + ' · ' + SECTION_LABEL[sec], title: ph[0], sub: ph[1] || SECTION_BLURB[sec] || '', size: 'lg', tag: 'h1', cls: 'ta-sh' }) + '<div class="ta-meta" id="meta-line"></div>'
      : '<h1>' + esc(ph[0]) + '</h1><div class="ta-meta" id="meta-line"></div>')) +
    (tabs.length > 1 && !detail ? '<nav class="qk-tabs ta-tabs" aria-label="' + esc(SECTION_LABEL[sec]) + ' pages">' + tabs.map(t =>
      '<a class="qk-tab" href="' + tabHref(t, T, Y) + '"' + (t[0] === r.name ? ' aria-selected="true" aria-current="page"' : ' aria-selected="false"') + '>' + esc(t[1]) + '</a>').join('') + '</nav>' : '');
  return bar;
}
/* Long detail pages (player, tournament) get a sticky "on this page" strip of their card titles. */
const JUMP_PAGES = ['player', 'event'];
function jumpNav(el, r) {
  if (JUMP_PAGES.indexOf(r.name) < 0) return;
  const build = () => {
    if (!el.isConnected) return;
    const heads = Array.prototype.slice.call(el.querySelectorAll('.card > .card-header, .qk-card > .qk-card-head')).filter(h => h.offsetParent);
    let nav = el.parentNode.querySelector('.ta-jump');
    if (heads.length < 4) { if (nav) nav.remove(); return; }
    if (!nav) { nav = document.createElement('nav'); nav.className = 'ta-jump'; nav.setAttribute('aria-label', 'On this page'); el.parentNode.insertBefore(nav, el); }
    const label = h => { const t = h.querySelector('.qk-card-title'); const raw = t ? t.textContent : (h.childNodes[0] ? h.childNodes[0].textContent : h.textContent); return String(raw || '').trim().slice(0, 34); };
    nav.innerHTML = '<div class="qk-chips scroll">' + heads.map((h, i) => '<button type="button" class="qk-chip" data-i="' + i + '">' + esc(label(h)) + '</button>').join('') + '</div>';
    nav.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      const c = heads[+b.dataset.i].closest('.card, .qk-card') || heads[+b.dataset.i];
      const off = ['.qk-topbar', '.qk-secnav'].reduce((a, q) => a + ((document.querySelector(q) || {}).offsetHeight || 0), 0) + nav.offsetHeight + 12;
      window.scrollTo({ top: c.getBoundingClientRect().top + window.scrollY - off, behavior: window.QK && QK.reducedMotion() ? 'auto' : 'smooth' });
    }));
  };
  setTimeout(build, 350);
  setTimeout(build, 1500);
  el.addEventListener('click', e => { if (e.target.closest && e.target.closest('.seg-tabs a, .tbtn, [role="tab"]')) setTimeout(build, 250); });
}
function showError(el, err) {
  console.error(err);
  if (el) el.insertAdjacentHTML('afterbegin', '<div class="error-banner" role="alert">This page could not be shown: ' + esc(err && err.message ? err.message : err) + '</div>');
}
function go(hash) {
  const h = hash.charAt(0) === '#' ? hash : '#/' + hash.replace(/^\/+/, '');
  if (location.hash === h) render(); else location.hash = h;
}

// ── loading ────────────────────────────────────────────────────────────────

/* Cached fetch of data/<path>. Resolves to the parsed JSON, or null when the file is
 * missing or broken. A payload written with "ok": false resolves as written: test with TA.ok(d). */
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
function ok(d) { return !!d && d.ok !== false; }
function reason(d) { return d && d.reason ? String(d.reason) : 'not built yet'; }
function cached(p0) { const p = String(p0).replace(/^data\//, ''); return Object.prototype.hasOwnProperty.call(CACHE, p) ? CACHE[p] : undefined; }
/* Per-tour payload path: tpath('rankings.json') -> 'atp/rankings.json'. */
function tpath(file, T) { return (isTour(T) ? T : state.tour) + '/' + file; }
/* Per-tour-year payload path: ypath('events.json') -> 'atp/2026/events.json'. */
function ypath(file, T, Y) {
  const t = isTour(T) ? T : state.tour;
  return t + '/' + (Y || (t === state.tour ? state.year : null) || currentYear(t)) + '/' + file;
}
function eventPath(T, id) { const a = args(arguments); return a[0] + '/events/' + a[1] + '.json'; }
function matchPath(T, id) { const a = args(arguments); return a[0] + '/matches/' + a[1] + '.json'; }
function playerPath(T, id) { const a = args(arguments); return a[0] + '/players/' + a[1] + '.json'; }
function loadTour(file, T) { return load(tpath(file, T)); }
function loadYear(file, T, Y) { return load(ypath(file, T, Y)); }

/* Names for a tour and the events of a year; resolves when both have loaded (or failed). */
function ensureTour(T, Y) {
  const t = isTour(T) ? T : state.tour;
  return loadAll([tpath('players_index.json', t), ypath('events.json', t, Y || currentYear(t))]);
}

/* players_index.json and <Y>/events.json come flat ({pid: [...]}, {event_id: {...}}) per PAYLOADS.md, or wrapped
 * with metadata ({"ok", "tour", ..., "players": {...}} / {"events": {...}}) as the builder writes them: accept both. */
function playersOf(d) { return d && d.players && typeof d.players === 'object' && !Array.isArray(d.players) ? d.players : (d || {}); }
function eventsOf(d) {
  if (!d || typeof d !== 'object') return {};
  if (d.events && typeof d.events === 'object' && !Array.isArray(d.events)) return d.events;
  const out = {};
  Object.keys(d).forEach(k => { if (d[k] && typeof d[k] === 'object' && !Array.isArray(d[k])) out[k] = d[k]; });
  return out;
}
/* Harvest names from any payload that carries them. */
function learn(p, d) {
  if (!d || typeof d !== 'object') return;
  const m = /^(atp|wta)\//.exec(p);
  // MATCH_CARDs may carry "n": [short1, short2]; names for players not in players_index yet
  const cardNames = (t, list) => (list || []).forEach(c => {
    if (!c || !Array.isArray(c.n)) return;
    [c.p1, c.p2].forEach((pid, i) => { if (pid && c.n[i] && !(NAMES[t][pid] || {}).name) NAMES[t][pid] = Object.assign({}, NAMES[t][pid] || {}, { name: c.n[i], short: c.n[i] }); });
  });
  try {
    if (p === 'index.json' && d.tours) TOURS.forEach(t => { const x = d.tours[t] || {}; ['live', 'today', 'recent', 'upcoming'].forEach(k => cardNames(t, x[k])); });
  } catch (e) { /* names are a convenience */ }
  const T = m ? m[1] : null;
  if (!T) return;
  const put = (id, info) => { if (!id || !info) return; NAMES[T][id] = Object.assign({}, NAMES[T][id] || {}, info); };
  try {
    if (/\/events\/[^/]+\.json$/.test(p) && d.draw && d.draw.matches) cardNames(T, Object.keys(d.draw.matches).map(k => d.draw.matches[k]));
    if (/\/schedule\.json$/.test(p)) cardNames(T, d.matches);
    if (/\/players_index\.json$/.test(p)) {
      const P = playersOf(d);
      Object.keys(P).forEach(id => { const r = P[id]; if (Array.isArray(r)) put(id, { name: r[0], short: r[1], country: r[2], rank: r[3] }); });
    }
    const ym = /^(atp|wta)\/(\d{4})\/events\.json$/.exec(p);
    if (ym) EVENTS[T][ym[2]] = Object.assign(EVENTS[T][ym[2]] || {}, eventsOf(d));
    if (/\/players\.json$/.test(p) && d.players && !Array.isArray(d.players)) {
      Object.keys(d.players).forEach(id => { const x = d.players[id] || {}; if (x.name && !(NAMES[T][id] || {}).name) put(id, { name: x.name, country: x.country }); });
    }
    if (/\/players\/[^/]+\.json$/.test(p) && d.name) put(String(d.id || p.split('/').pop().replace('.json', '')), { name: d.name, country: d.country });
    if (/\/events\/[^/]+\.json$/.test(p) && d.event && d.event.id) {
      const y = String(yearOfId(d.event.id) || '');
      if (y) { EVENTS[T][y] = EVENTS[T][y] || {}; EVENTS[T][y][d.event.id] = Object.assign({}, d.event, EVENTS[T][y][d.event.id] || {}); }
    }
    if (d.names && typeof d.names === 'object' && !Array.isArray(d.names)) {
      Object.keys(d.names).forEach(id => { const n = d.names[id]; if (typeof n === 'string' && !(NAMES[T][id] || {}).name) put(id, { name: n }); });
    }
  } catch (e) { console.warn('learn failed for', p, e); }
}

// ── formatting ─────────────────────────────────────────────────────────────

function isNum(v) { return v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v); }
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
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
function fmtSec(s) {
  if (!isNum(s)) return '—';
  let t = Math.round(Math.abs(Number(s)));
  const h = Math.floor(t / 3600); t -= h * 3600;
  const m = Math.floor(t / 60); t -= m * 60;
  const p2 = n => (n < 10 ? '0' : '') + n;
  return (s < 0 ? '-' : '') + (h ? h + ':' + p2(m) : m) + ':' + p2(t);
}
/* Match length in minutes as "2h 14m". */
function fmtDuration(min) {
  if (!isNum(min)) return '—';
  const m = Math.round(Number(min)), h = Math.floor(m / 60);
  return h ? h + 'h ' + String(m - h * 60).padStart(2, '0') + 'm' : m + 'm';
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
function parseDate(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  let str = String(s);
  if (/^\d{8}$/.test(str)) str = str.slice(0, 4) + '-' + str.slice(4, 6) + '-' + str.slice(6);
  // "2026-10-03T04:00" without a zone is UTC (ESPN times)
  if (/^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?$/.test(str)) str += 'Z';
  const d = new Date(str.length === 10 ? str + 'T12:00:00Z' : str);
  return isNaN(d.getTime()) ? null : d;
}
/* fmtDate("2026-10-20") -> "Tue 20 Oct 2026" (viewer's timezone). opts {year:false, time:true, weekday:false}. */
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
  if (!d || String(s).length <= 10) return '';
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function fmtStamp(s) {
  const d = parseDate(s);
  if (!d) return s ? String(s) : '';
  return fmtDate(d, { year: false }) + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
/* "28 Sep – 11 Oct" for an event's dates. */
function fmtRange(a, b) {
  const x = parseDate(a), y = parseDate(b);
  if (!x) return '—';
  if (!y) return fmtDate(a, { weekday: false, year: false });
  const same = x.getMonth() === y.getMonth();
  return x.getDate() + (same ? '' : ' ' + MONTHS[x.getMonth()]) + '–' + y.getDate() + ' ' + MONTHS[y.getMonth()];
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
/* Format a catalogue value by its METRIC fmt: int|0|1|2|3|pct|prob|signed (PAYLOADS.md). */
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
    case '0': return x.toFixed(0);
    case '1': return x.toFixed(1);
    case '3': return x.toFixed(3).replace(/^0\./, '.').replace(/^-0\./, '-.');
    default: return x.toFixed(2);
  }
}
function metric(list, key) { return (list || []).find(m => m && m.key === key) || null; }
function record(w, l) { return isNum(w) && isNum(l) ? Math.round(w) + '-' + Math.round(l) : '—'; }
/* Fair American odds of a probability: 0.6 -> "-150". */
function american(p) {
  if (!isNum(p) || p <= 0 || p >= 1) return '—';
  return p >= 0.5 ? '-' + Math.round(100 * p / (1 - p)) : '+' + Math.round(100 * (1 - p) / p);
}
/* Fair decimal odds: 0.4 -> "2.50". */
function decimal(p) { return isNum(p) && p > 0 ? (1 / p).toFixed(p > 0.1 ? 2 : 1) : '—'; }
/* Market sources come as names ('kalshi') or as records ({source, p1, ...}); either way, display names. */
function sourceNames(list) {
  var N = { kalshi: 'Kalshi', polymarket: 'Polymarket', pinnacle: 'Pinnacle', betfair: 'Betfair', avg: 'Bookmaker average', b365: 'Bet365' };
  var out = [];
  (list || []).forEach(function (x) { var k = typeof x === 'string' ? x : ((x && (x.source || x.name)) || ''); var n = N[k] || k; if (n && out.indexOf(n) < 0) out.push(n); });
  return out;
}
/* Two-way decimal odds [o1, o2] -> de-vigged p1 (null when missing). */
function devig2(o) {
  if (!o || !isNum(o[0]) || !isNum(o[1]) || o[0] <= 1 || o[1] <= 1) return null;
  const a = 1 / o[0], b = 1 / o[1];
  return a / (a + b);
}
function titleCase(id) {
  return String(id || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

// ── tennis vocabulary ──────────────────────────────────────────────────────

/* Surface colour; indoor hard is purple. */
function surfaceColour(s, indoor) {
  if (indoor && (s === 'hard' || !s || s === 'indoor')) return C.indoor;
  return C[s] || C.text3;
}
function surfaceLabel(s, indoor) {
  if (indoor && (s === 'hard' || s === 'indoor')) return 'Indoor hard';
  return SURFACE_LABEL[s] || titleCase(s || '—') + (indoor ? ' (indoor)' : '');
}
function surfaceDot(s, indoor) { return '<span class="sf-dot" style="background:' + surfaceColour(s, indoor) + '" title="' + esc(surfaceLabel(s, indoor)) + '"></span>'; }
function surfaceChip(s, indoor) {
  const c = surfaceColour(s, indoor);
  return '<span class="chip sf-chip" style="border-color:' + c + ';color:' + c + '">' + esc(surfaceLabel(s, indoor)) + '</span>';
}
function levelLabel(level, T) {
  const t = isTour(T) ? T : state.tour;
  const map = { slam: 'Grand Slam', finals: t === 'atp' ? 'ATP Finals' : 'WTA Finals', m1000: t === 'atp' ? 'Masters 1000' : 'WTA 1000',
    '500': t === 'atp' ? 'ATP 500' : 'WTA 500', '250': t === 'atp' ? 'ATP 250' : 'WTA 250', other: 'Other', ch: t === 'atp' ? 'Challenger' : 'WTA 125', q: 'Qualifying' };
  return map[String(level)] || titleCase(level || '');
}
function levelShort(level) { return { slam: 'GS', finals: 'Finals', m1000: '1000', '500': '500', '250': '250', other: 'Other', ch: '125/CH', q: 'Q' }[String(level)] || String(level || ''); }
function levelChip(level, T) { return '<span class="chip lv-chip lv-' + esc(level) + '">' + esc(levelLabel(level, T)) + '</span>'; }
function levelRank(level) { const i = LEVELS.indexOf(String(level)); return i < 0 ? 99 : i; }
function roundLabel(r, short) { return (short ? ROUND_SHORT : ROUND_LONG)[r] || String(r || '—'); }
function roundIndex(r) { const i = ROUND_ORDER.indexOf(r); return i < 0 ? (r === 'W' ? 99 : -1) : i; }

/* Status of a MATCH_CARD / match: 'live' | 'pre' | 'done' | 'ret' | 'wo' | 'def' | other. */
function matchState(m) {
  const s = String((m && m.status) || '').toLowerCase();
  if (s === 'live' || s === 'in') return 'live';
  if (s === 'upcoming' || s === 'pre' || s === 'scheduled' || !s) return 'pre';
  if (s === 'done' || s === 'final' || s === 'post') return 'done';
  return s;
}
function isFinished(m) { const s = matchState(m); return s === 'done' || s === 'ret' || s === 'wo' || s === 'def'; }
/* Set score of a match from p1's view, or from the winner's view with {winner: true}.
 * Tiebreak points go in a superscript: the loser's points of the tiebreak ("7-6<sup>5</sup>").
 * opts {winner, html:true, live (append the current set from m.live), status:true (ret./w/o)}. */
function fmtScore(m, opts) {
  const o = opts || {};
  const html = o.html !== false;
  if (!m) return '—';
  const sets = (Array.isArray(m) ? m : m.sets) || [];
  const flip = !!o.winner && m.winner && m.p2 && m.winner === m.p2;
  const parts = sets.map(s => {
    if (!s) return '';
    let a = s[0], b = s[1], ta = s[2], tb = s[3];
    if (flip) { a = s[1]; b = s[0]; ta = s[3]; tb = s[2]; }
    let tbTxt = '';
    if (isNum(ta) || isNum(tb)) {
      const lo = isNum(ta) && isNum(tb) ? Math.min(ta, tb) : (isNum(ta) ? ta : tb);
      tbTxt = html ? '<sup>' + lo + '</sup>' : '(' + lo + ')';
    }
    return a + '-' + b + tbTxt;
  }).filter(Boolean);
  if (o.live !== false && m.live && matchState(m) === 'live' && m.live.games) {
    const g = m.live.games;
    const cur = flip ? g[1] + '-' + g[0] : g[0] + '-' + g[1];
    if (!sets.length || sets.length < (m.live.set || 0)) parts.push(html ? '<span class="sc-cur">' + cur + '</span>' : cur);
  }
  const st = matchState(m);
  let tail = '';
  if (o.status !== false) {
    if (st === 'ret') tail = ' ret.';
    else if (st === 'wo') tail = 'w/o';
    else if (st === 'def') tail = ' def.';
  }
  return (parts.join(' ') + tail).trim() || (st === 'wo' ? 'w/o' : '—');
}
/* Sets won by each side: [s1, s2]. */
function setsWon(m) {
  const out = [0, 0];
  ((m && m.sets) || []).forEach(s => {
    if (!s) return;
    if (s[0] > s[1]) out[0] += 1; else if (s[1] > s[0]) out[1] += 1;
  });
  return out;
}
function totalGames(m) { return ((m && m.sets) || []).reduce((a, s) => a + (s ? (s[0] || 0) + (s[1] || 0) : 0), 0); }
/* A status chip: start time, live set and games, Final / Ret. / W/O. */
function statusChip(m) {
  const st = matchState(m);
  if (st === 'live') {
    const lv = m.live || {};
    return '<span class="chip st-live"><span class="live-dot"></span> Live' + (lv.set ? ' · set ' + esc(lv.set) : '') + '</span>';
  }
  if (st === 'done') return '<span class="chip st-ft">Final</span>';
  if (st === 'ret') return '<span class="chip st-ft">Ret.</span>';
  if (st === 'wo') return '<span class="chip st-ft">Walkover</span>';
  if (st === 'def') return '<span class="chip st-ft">Default</span>';
  if (st === 'pre') return '<span class="chip st-time">' + esc(fmtTime(m.date) || 'TBD') + '</span>';
  return '<span class="chip warn">' + esc(titleCase(st)) + '</span>';
}
/* A short text for an award's numbers: p_pre / p (won from x% pre-match), min_p (comeback), wins_over_exp,
 * tb_w/tb_l (tiebreak record), value; '' when none. */
function awardValue(a) {
  if (!a || typeof a !== 'object') return '';
  if (isNum(a.p_pre)) return 'won from ' + pct(a.p_pre, 0) + ' pre-match';
  if (isNum(a.min_p)) return 'won from ' + pct(a.min_p, 0) + ' at worst';
  if (isNum(a.p) && a.p < 1) return 'won from ' + pct(a.p, 0) + ' pre-match';
  if (isNum(a.wins_over_exp)) return signed(a.wins_over_exp, 2) + ' wins over expected';
  if (isNum(a.tb_w) && isNum(a.tb_l)) return a.tb_w + '-' + a.tb_l + ' in tiebreaks';
  if (isNum(a.games_share)) return pct(a.games_share, 0) + ' of the games';
  if (isNum(a.value)) return num(a.value, 2);
  const k = Object.keys(a).find(x => isNum(a[x]) && x !== 'set' && x !== 'winner' && x !== 'pid');
  return k ? titleCase(k) + ' ' + (Math.abs(a[k]) <= 1 && !Number.isInteger(a[k]) ? pct(a[k], 0) : num(a[k], Number.isInteger(a[k]) ? 0 : 2)) : '';
}
/* A market TITLE dict -> {pid: p} (de-vigged "probs", else "prices", else the raw "mid"); {} when unavailable. */
function titleProbs(t) {
  if (!t || t.available === false) return {};
  return t.probs || t.prices || t.mid || {};
}

// ── names, events, links ───────────────────────────────────────────────────

/* Normalise (T, id, ...rest) when the tour was left out: (id, ...rest). */
function args(a) {
  const list = Array.prototype.slice.call(a);
  if (isTour(list[0])) return list;
  return [state.tour].concat(list);
}
function player(T, id) { const a = args(arguments); return NAMES[a[0]][String(a[1])] || {}; }
function playerName(T, id) { const a = args(arguments); const x = NAMES[a[0]][String(a[1])]; return x && x.name ? x.name : (a[1] ? 'Player ' + a[1] : '—'); }
function playerShort(T, id) {
  const a = args(arguments); const x = NAMES[a[0]][String(a[1])] || {};
  if (x.short) return x.short;
  const n = playerName(a[0], a[1]).split(' ');
  return n.length > 1 ? n[0].charAt(0) + '. ' + n.slice(1).join(' ') : n[0];
}
/* Surname (last token of the name unless "short" gives "J. Surname"). */
function playerSurname(T, id) {
  const a = args(arguments); const s = playerShort(a[0], a[1]);
  return s.replace(/^([A-Z][a-z]?\.\s*)+/, '') || s;
}
function playerCountry(T, id) { const a = args(arguments); return (NAMES[a[0]][String(a[1])] || {}).country || ''; }
function playerRank(T, id) { const a = args(arguments); const r = (NAMES[a[0]][String(a[1])] || {}).rank; return isNum(r) ? Number(r) : null; }
/* A stable colour per player (for multi-line charts). */
function hashIndex(s, n) { let h = 0; String(s).split('').forEach(ch => { h = (h * 31 + ch.charCodeAt(0)) >>> 0; }); return h % n; }
function playerColour(T, id) { const a = args(arguments); return a[1] ? PALETTE[hashIndex(a[1], PALETTE.length)] : C.text3; }
/* '?y=Y' when Y is not the tour's current year, else ''. */
function yq(T, Y) {
  const t = isTour(T) ? T : state.tour;
  const y = Y || (t === state.tour ? state.year : null);
  return y && Number(y) !== currentYear(t) ? '?y=' + y : '';
}
/* '#/<T>/<sub>' plus the year query: href('atp', 'rankings') -> '#/atp/rankings'. */
function href(T, sub, Y) {
  const t = isTour(T) ? T : state.tour;
  const s = String(sub || '').replace(/^\/+/, '');
  return '#/' + t + (s ? '/' + s : '') + (s ? yq(t, Y) : '');
}
function playerHref(T, id, Y) { const a = args(arguments); return href(a[0], 'player/' + encodeURIComponent(a[1]), a[2]); }
function eventHref(T, id) { const a = args(arguments); return '#/' + a[0] + '/event/' + encodeURIComponent(a[1]); }
function matchHref(T, id) { const a = args(arguments); return '#/' + a[0] + '/match/' + encodeURIComponent(a[1]); }
function h2hHref(T, x, y) { const a = args(arguments); return '#/' + a[0] + '/h2h' + (a[1] ? '/' + encodeURIComponent(a[1]) : '') + (a[2] ? '/' + encodeURIComponent(a[2]) : ''); }
function compareHref(T, x, y) { const a = args(arguments); return '#/' + a[0] + '/compare' + (a[1] ? '/' + encodeURIComponent(a[1]) : '') + (a[2] ? '/' + encodeURIComponent(a[2]) : ''); }
/* <a> to the player page. opts {name, short: true, surname: true, rank: true (official rank prefix), seed, country: true, year} or a name string. */
function playerLink(T, id, opts) {
  const a = args(arguments);
  if (!a[1]) return '<span class="muted-inline">—</span>';
  const o = typeof a[2] === 'string' ? { name: a[2] } : (a[2] || {});
  const label = o.name || (o.surname ? playerSurname(a[0], a[1]) : o.short ? playerShort(a[0], a[1]) : playerName(a[0], a[1]));
  const rk = o.rank ? playerRank(a[0], a[1]) : null;
  const pre = isNum(o.seed) ? '<span class="seed">[' + esc(o.seed) + ']</span>' : (rk ? '<span class="seed">' + rk + '</span>' : '');
  const cc = o.country ? playerCountry(a[0], a[1]) : '';
  return '<a class="ply-link" href="' + playerHref(a[0], a[1], o.year) + '">' + pre + esc(label) + (cc ? '<span class="ctry">' + esc(cc) + '</span>' : '') + '</a>';
}
/* Event record from events.json of its year (name, level, surface, indoor, start, end, status, champion...). */
function eventInfo(T, id) {
  const a = args(arguments);
  const y = String(yearOfId(a[1]) || '');
  return ((EVENTS[a[0]][y] || {})[a[1]]) || {};
}
function eventName(T, id, withYear) {
  const a = args(arguments);
  const e = eventInfo(a[0], a[1]);
  const y = yearOfId(a[1]);
  const base = e.name || titleCase(String(a[1] || '').replace(/-(19|20)\d\d$/, ''));
  return a[2] && y ? base + ' ' + y : base;
}
/* <a> to the tournament page. opts {name, year: true (append the year), surface: true (dot)} or a name string. */
function eventLink(T, id, opts) {
  const a = args(arguments);
  if (!a[1]) return '<span class="muted-inline">—</span>';
  const o = typeof a[2] === 'string' ? { name: a[2] } : (a[2] || {});
  const e = eventInfo(a[0], a[1]);
  return '<a class="ev-link" href="' + eventHref(a[0], a[1]) + '">' + (o.surface && e.surface ? surfaceDot(e.surface, e.indoor) : '') + esc(o.name || eventName(a[0], a[1], o.year)) + '</a>';
}
/* <a> to the match centre (label default "Match centre"). */
function matchLink(T, id, label) {
  const a = args(arguments);
  if (!a[1]) return '<span class="muted-inline">—</span>';
  return '<a class="game-link match-link" href="' + matchHref(a[0], a[1]) + '">' + esc(a[2] || 'Match centre') + '</a>';
}

/* A MATCH_CARD as the kit's game card (index.json live/today/recent/upcoming, schedule, draws), linking to the match
 * centre (Design System 2.0 game card): both players with rank and set scores, our win chance before the first ball (the
 * favourite in the signal colour), sets won once it starts, our win-chance bar, and the likeliest score and expected games.
 * opts {tour, date: true (show the date), event: true (show the event name), compact, round: true}. */
function playerObj(T, pid) { const x = NAMES[T][String(pid)] || {}; return { name: playerShort(T, pid), abbr: (x.country || '').slice(0, 3) || fmtInitials(playerName(T, pid)), href: playerHref(T, pid) }; }
function fmtInitials(n) { const p = String(n || '?').split(' '); return (p.length > 1 ? p[0][0] + p[p.length - 1][0] : p[0].slice(0, 2)).toUpperCase(); }
function matchCard(c, opts) {
  const o = opts || {};
  const T = o.tour || state.tour;
  if (!c) return '';
  const st = matchState(c);
  const m = c.model || {};
  const p1 = isNum(m.p1) ? Number(m.p1) : null;
  const live = st === 'live', fin = isFinished(c), pre = !live && !fin;
  const pShow = live && isNum(c.wp_now) ? Number(c.wp_now) : p1;
  const sets = c.sets || [];
  const lv = c.live || null;
  const nSets = Math.max(sets.length + (live && lv && lv.games && sets.length < (lv.set || 0) ? 1 : 0), 0);
  const won = setsWon(c);
  const fav1 = isNum(pShow) && pShow >= 0.5;
  const row = (pid, side, p) => {
    const win = fin && c.winner === pid;
    let cells = '';
    for (let i = 0; i < nSets; i++) {
      const s = sets[i];
      let g, tb = '', cls = 'ta-set';
      if (s) {
        g = s[side]; const og = s[1 - side];
        if (g > og) cls += ' won';
        if (isNum(s[2 + side]) && g < og) tb = '<sup>' + s[2 + side] + '</sup>';
      } else if (lv && lv.games) { g = lv.games[side]; cls += ' cur'; }
      cells += '<span class="' + cls + '">' + (isNum(g) ? g : '') + tb + '</span>';
    }
    const rk = playerRank(T, pid);
    const cc = playerCountry(T, pid);
    const v = pre ? '<span class="qk-gc-v pct" title="Our win chance">' + (isNum(p) ? pct(p, 0) : '') + '</span>'
      : '<span class="qk-gc-v" title="Sets won">' + (sets.length || live ? won[side] : '–') + '</span>';
    return '<div class="qk-gc-row ta-gcrow' + (fin && c.winner && !win ? ' lost' : '') + (pre && (side === 0) === fav1 && isNum(p) ? ' fav' : '') + '">' +
      '<span class="ta-rank" title="Ranking">' + (isNum(rk) ? rk : '') + '</span>' +
      '<span class="qk-gc-nm">' + esc(playerShort(T, pid)) + (cc ? '<small>' + esc(cc) + '</small>' : '') + (win ? ' <span class="ta-win" aria-label="winner">✓</span>' : '') + '</span>' +
      '<span class="ta-sets">' + cells + '</span>' + v + '</div>';
  };
  let badge;
  if (live) badge = '<span class="qk-badge live">Live' + (lv && lv.set ? ' · Set ' + lv.set : '') + '</span>';
  else if (fin) badge = '<span class="qk-badge final">' + (st === 'ret' ? 'Ret.' : st === 'wo' ? 'W/O' : 'Final') + '</span>';
  else {
    const tba = c.tba || (c.date && String(c.date).length <= 10);
    badge = '<span class="qk-badge"' + (tba ? ' title="Start time to be announced"' : '') + '>' + esc((o.date !== false ? fmtDate(c.date, { year: false, weekday: false }) + ' ' : '') + (tba ? 'TBA' : (fmtTime(c.date) || 'TBA'))) + '</span>';
  }
  const tag = (o.event !== false ? eventName(T, c.event) + ' · ' : '') + roundLabel(c.round, true);
  const A = { name: playerShort(T, c.p1), abbr: playerSurname(T, c.p1) }, B = { name: playerShort(T, c.p2), abbr: playerSurname(T, c.p2) };
  const bar = !fin && pShow !== null && window.QK ? QK.wpBar(pShow, null, 1 - pShow, A, B, { label: live ? 'Live win chance' : 'Our win chance' }) : '';
  const bits = [];
  if (pre && isNum(p1)) bits.push('<span class="ours">Our chance</span>');
  else if (live && isNum(c.wp_now)) bits.push('<span class="ours">Live chance</span>');
  else if (fin && isNum(p1)) bits.push('<span>Before: <b>' + esc(playerSurname(T, p1 >= 0.5 ? c.p1 : c.p2)) + ' ' + pct(Math.max(p1, 1 - p1), 0) + '</b></span>');
  const top1 = (m.sets_dist_top || [])[0];
  if (top1 && pre) bits.push('<span title="Likeliest score in sets">Likeliest <b>' + esc(top1[0]) + '</b> ' + pct(top1[1], 0) + '</span>');
  if (isNum(m.exp_games) && pre) bits.push('<span title="Expected games in the match">Games <b>' + num(m.exp_games, 1) + '</b></span>');
  /* v3: opts.why adds the italic one-line reason (QK.whyLine on the kit shape: a coin flip, a clear favourite and how
     often that still goes wrong, an upset, a live match the score has moved). */
  const why = o.why && window.QK && QK.whyLine ? QK.whyLine(kitGame(c, T)) : '';
  return '<a class="qk-gc ta-mc' + (live ? ' is-live' : fin ? ' is-final' : '') + (o.compact ? ' gc-compact' : '') + '" href="' + matchHref(T, c.id) + '" style="--sa:var(--a-tennis)">' +
    '<div class="qk-gc-top"><span class="qk-gc-lg">' + esc(tag) + '</span>' + badge + '</div>' +
    '<div class="qk-gc-rows">' + row(c.p1, 0, pShow) + row(c.p2, 1, pShow === null ? null : 1 - pShow) + '</div>' + bar +
    (bits.length ? '<div class="qk-gc-foot">' + bits.join('') + '</div>' : '') + (why ? '<div class="qk-aside">' + esc(why) + '</div>' : '') + '</a>';
}
/* A MATCH_CARD as the kit's game shape (ticker, feature card, preview card, "why" lines): p1 on the top row (away),
 * p2 below (home); p_home is our pre-match chance for p2 (kept after the match as the pre-match call), wp_home the live
 * one; as / hs are sets won. No market: the kit shows it only where a page asks. opts.initials: the monogram reads the
 * player's initials (feature and preview cards) instead of the surname (ticker, bar keys). */
function kitGame(c, T0, opts) {
  const T = T0 || state.tour, ko = opts || {};
  const st = matchState(c), fin = isFinished(c), live = st === 'live';
  const m = c.model || {};
  const w = setsWon(c);
  const ent = pid => { const x = NAMES[T][String(pid)] || {}; return { name: playerShort(T, pid), abbr: ko.initials ? fmtInitials(playerName(T, pid)) : playerSurname(T, pid).slice(0, 12), href: playerHref(T, pid), country: x.country || '' }; };
  const d = parseDate(c.date);
  return { sport: 'tennis', league: eventName(T, c.event), note: roundLabel(c.round), id: c.id, start: d ? d.toISOString() : c.date, status: live ? 'live' : fin ? 'final' : 'pre',
    away: ent(c.p1), home: ent(c.p2), as: fin || live ? w[0] : null, hs: fin || live ? w[1] : null,
    p_home: isNum(m.p1) ? 1 - Number(m.p1) : null, wp_home: live && isNum(c.wp_now) ? 1 - Number(c.wp_now) : undefined,
    pre_only: live && !isNum(c.wp_now) ? true : undefined, href: matchHref(T, c.id), tba: !!c.tba || (c.date && String(c.date).length <= 10) };
}
/* Before the first ball a card is "upcoming"; a snapshot can keep a match live or upcoming long after it was played.
 * Cards still live or upcoming 12 hours after their start are dropped (the Home page applies the same guard). */
function fresh(list) {
  const cut = (window.QK && QK.now ? QK.now() : Date.now()) - 12 * 3600e3;
  return (list || []).filter(c => {
    if (!c) return false;
    if (isFinished(c)) return true;
    const d = parseDate(c.date);
    return !d || d.getTime() >= cut;
  });
}

// ── tours and years ────────────────────────────────────────────────────────

function tourInfo(T) {
  const t = isTour(T) ? T : state.tour;
  const d = INDEX.data;
  return (d && d.tours && d.tours[t]) || {};
}
function currentYear(T) {
  const i = tourInfo(T);
  return i.year ? Number(i.year) : new Date().getFullYear();
}
function years(T) {
  const t = isTour(T) ? T : state.tour;
  const i = tourInfo(t);
  const list = (i.years && i.years.length ? i.years.map(Number) : [currentYear(t)]).slice();
  if (list.indexOf(currentYear(t)) < 0) list.push(currentYear(t));
  return list.sort((a, b) => b - a);
}
function tourName(T) { return TOUR_NAME[isTour(T) ? T : state.tour]; }

// ── HTML builders ──────────────────────────────────────────────────────────

/* A kit card: title and subtitle over the body (bodies keep their own padding classes: .pad, tables flush). */
function card(title, sub, bodyHtml, id) {
  return '<section class="qk-card card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' +
    (title ? '<div class="qk-card-head card-header"><div><div class="qk-card-title">' + esc(title) + '</div>' + (sub ? '<div class="qk-card-sub card-sub">' + sub + '</div>' : '') + '</div></div>' : '') +
    '<div class="card-main">' + (bodyHtml || '') + '</div></section>';
}
function muted(text) { return '<div class="muted">' + text + '</div>'; }
function chip(text, cls) { return '<span class="chip' + (cls ? ' ' + cls : '') + '">' + esc(text) + '</span>'; }
function notBuilt(what, d) { return muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '.'); }

/* Table. cols: [{label, align, title, sortable:false, cls}]. rows: [{cells, _class, _href}] or arrays of cells;
 * a cell is {v, html, cls, align, title, style} or a primitive. opts {compact, sticky, cls, id}. */
function tableHTML(cols, rows, opts) {
  const o = opts || {};
  let h = '<div class="table-wrap qk-table-wrap' + (o.compact ? ' compact' : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><table class="qk-table wc-table' + (o.compact ? ' dense' : '') + (o.sticky ? ' sticky-head' : '') + (o.cls ? ' ' + o.cls : '') + '"><thead><tr>';
  cols.forEach(c => {
    const cc = typeof c === 'string' ? { label: c } : c;
    h += '<th class="' + (cc.sortable === false ? '' : 'sortable-th') + (cc.cls ? ' ' + cc.cls : '') + '"' +
         (cc.align ? ' style="text-align:' + cc.align + '"' : '') + (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>';
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
/* Percentiles on the kit's diverging scale, the same on every site: red (poor) through the neutral to blue (great); p is 0-100. */
function tokenOf(n, dflt) { const v = window.QK ? QK.cssVar(n) : ''; return v || dflt; }
/* Percentiles on the kit's v2 scale (Savant-like, cold blue = worst in the peer group, hot red = best); p is 0-100. */
function pctColor(p) {
  if (!isNum(p)) return 'var(--s-3)';
  return window.QK && QK.pctColor ? QK.pctColor(p) : 'var(--pc-50)';
}
function pctInk(p) { return isNum(p) && window.QK && QK.pctInk ? QK.pctInk(p) : 'var(--ink-1)'; }
function pctPill(p) {
  if (!isNum(p)) return '<span class="pct-pill empty">—</span>';
  return '<span class="pct-pill" style="background:' + pctColor(p) + ';color:' + pctInk(p) + '">' + Math.round(p) + '</span>';
}
function pctRow(label, p, valueText, title) {
  const known = isNum(p);
  const x = known ? Math.max(0, Math.min(100, p)) : 0;
  return '<div class="pct-row"' + (title ? ' title="' + esc(title) + '"' : '') + '>' +
    '<span class="pct-label">' + esc(label) + '</span>' +
    '<div class="pct-bar">' + (known
      ? '<div class="pct-fill" style="width:' + x + '%;background:' + pctColor(p) + '"></div>' +
        '<span class="pct-dot" style="left:' + x + '%;background:' + pctColor(p) + ';color:' + pctInk(p) + '">' + Math.round(p) + '</span>'
      : '<span class="pct-none">not enough data</span>') +
    '</div><span class="pct-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
}
/* A v2 stat tile (kit .qk-stat). statTile(label, valueHTML, subHTML, cls), or statTile({ QK.statTile options }). A value
 * that is a number reads in the display face; a name or a list reads as text. */
function statTile(label, value, sub, cls) {
  if (label && typeof label === 'object') return window.QK ? QK.statTile(label) : '';
  const v = value === undefined || value === null || value === '' ? '—' : String(value);
  const plain = v.replace(/<[^>]*>/g, '').trim();
  const numeric = /^[−+\-–]?[\d.,]+\s?(%|pts?|×)?$/.test(plain) || /^[\d.]+ v [\d.]+$/.test(plain);
  return '<div class="qk-stat kpi' + (cls ? ' ' + cls : '') + '"><div class="qk-stat-label"><span>' + esc(label) + '</span></div>' +
    '<div class="qk-stat-v' + (numeric ? '' : ' text') + '">' + v + '</div>' + (sub ? '<div class="qk-stat-sub"><span>' + sub + '</span></div>' : '') + '</div>';
}
/* A probability with an inline bar (0-1); colour optional; max scales the bar. */
function probCell(p, colour, max) {
  if (!isNum(p)) return '<span class="muted-inline">—</span>';
  const w = Math.max(0, Math.min(1, p / (max || 1))) * 100;
  return '<span class="pcell"><span class="pcell-bar"><span style="width:' + w.toFixed(1) + '%;background:' + (colour || 'var(--c-1)') + '"></span></span><span class="pcell-v">' + pct(p) + '</span></span>';
}
/* Model minus market in percentage points, coloured (green = model higher). */
function edgeHTML(model, market, d) {
  if (!isNum(model) || !isNum(market)) return '<span class="muted-inline">—</span>';
  const e = (model - market) * 100;
  return '<span class="' + (e > 0.05 ? 'edge-pos' : e < -0.05 ? 'edge-neg' : 'muted-inline') + '">' + signed(e, d === undefined ? 1 : d) + '</span>';
}
/* A two-sided probability bar: p1 share in the p1 colour, the rest in the p2 colour; opts {labels:[a,b], market}. */
function splitBar(p, opts) {
  const o = opts || {};
  if (!isNum(p)) return '<div class="split-bar empty"></div>';
  const w = Math.max(0, Math.min(1, p)) * 100;
  return '<div class="split-bar"><span class="sb-a" style="width:' + w.toFixed(1) + '%"></span><span class="sb-b" style="width:' + (100 - w).toFixed(1) + '%"></span>' +
    (isNum(o.market) ? '<i class="sb-mk" style="left:' + (Math.max(0, Math.min(1, o.market)) * 100).toFixed(1) + '%" title="Market ' + pct(o.market) + '"></i>' : '') + '</div>';
}
function divColour(v, max, invert) {
  if (!isNum(v) || !max) return 'transparent';
  let t = Math.max(-1, Math.min(1, v / max));
  if (invert) t = -t;
  const a = Math.abs(t);
  return t < 0 ? 'color-mix(in srgb, var(--up) ' + Math.round(12 + 60 * a) + '%, transparent)' : 'color-mix(in srgb, var(--down) ' + Math.round(12 + 60 * a) + '%, transparent)';
}
/* Sequential colour for t in [0,1] (the ace yellow-green). */
function seqColour(t) {
  if (!isNum(t)) return 'transparent';
  const u = Math.max(0, Math.min(1, t));
  return 'color-mix(in srgb, var(--accent) ' + Math.round(5 + 75 * u) + '%, transparent)';
}
function toggles(items, active, attr) {
  const a = attr || 'data-k';
  return items.map(it => { const on = String(it.key) === String(active); return '<button type="button" class="tbtn' + (on ? ' active' : '') + '" aria-pressed="' + on + '" ' + a + '="' + esc(it.key) + '">' + esc(it.label) + '</button>'; }).join('');
}
function wireToggles(root, attr, fn) {
  if (!root) return;
  const a = attr || 'data-k';
  root.querySelectorAll('[' + a + ']').forEach(b => b.addEventListener('click', () => {
    root.querySelectorAll('[' + a + ']').forEach(x => { x.classList.toggle('active', x === b); x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
    fn(b.getAttribute(a));
  }));
}
/* A v2 section head inside a page: title, an HTML sub-line, links or controls on the right. */
function pageHead(title, sub, right, kicker) {
  if (window.QK && QK.sectionHead) return QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right ? '<div class="ph-nav">' + right + '</div>' : '', html: true, cls: 'page-head' });
  return '<div class="page-head"><div><h2>' + esc(title) + '</h2>' + (sub ? '<div class="ph-sub">' + sub + '</div>' : '') + '</div>' +
    (right ? '<div class="ph-nav">' + right + '</div>' : '') + '</div>';
}

// ── header: tour switch, year picker, nav, meta, search ────────────────────

function setTourState(T) {
  if (!isTour(T)) return;
  state.tour = T;
  try { window.localStorage.setItem(LS_TOUR, T); } catch (e) { /* private mode */ }
}
/* Switch tour, keeping the page type where it makes sense. */
function switchTour(T) {
  if (!isTour(T)) return;
  const r = state.route || 'hub';
  let to = SWITCH_TO[r] || r;
  if (to === 'notfound' || !routeEntry(to)) to = 'hub';
  if ((routeEntry(to) || {}).global) {
    setTourState(T);
    const h = String(location.hash || '#/').replace(/^#\/(atp|wta)\//, '#/');
    if (h !== location.hash) go(h); else render();
    return;
  }
  if (to === 'hub') go('#/' + T);
  else go('#/' + T + '/' + routeEntry(to).pattern.replace(/\/:.*$/, ''));
}
/* Change the year shown, keeping the page where it makes sense. */
function setYear(Y) {
  const y = parseInt(Y, 10);
  if (isNaN(y)) return;
  const T = state.tour, r = state.route || 'hub';
  if (r === 'event' || r === 'match') { go(href(T, 'calendar', y)); return; }
  if ((routeEntry(r) || {}).global) { state.year = y; return; }
  const h = String(location.hash || '#/' + T).replace(/\?.*$/, '');
  const q = Object.assign({}, state.params.query || {});
  if (y === currentYear(T)) delete q.y; else q.y = String(y);
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  go((h === '#/' || h === '#' ? '#/' + T : h) + (qs ? '?' + qs : ''));
}
let pickerFilled = false;
let SHELL = null;
/* The tour switch and year picker sit at the right of the section nav (the shell's ctx slot). */
function ctxHTML() {
  return '<div class="qk-seg ta-tour" role="group" aria-label="Tour">' + TOURS.map(t =>
    '<button type="button" data-tour="' + t + '" aria-pressed="' + (t === state.tour) + '">' + esc(TOUR_NAME[t]) + '</button>').join('') + '</div>' +
    '<select class="qk-select ta-year" id="year-select" aria-label="Year"></select>';
}
function fillYearPicker() {
  const sel = document.getElementById('year-select');
  if (!sel) return;
  const T = state.tour;
  const list = years(T);
  if (state.year && list.indexOf(state.year) < 0) list.unshift(state.year);
  sel.innerHTML = list.map(y => '<option value="' + y + '">' + y + '</option>').join('');
  sel.value = String(state.year || currentYear(T));
  pickerFilled = true;
}
function sectionHrefs(T, Y) {
  return { overview: '#/' + T + yq(T, Y), fixtures: href(T, 'calendar', Y), standings: href(T, 'rankings', Y), players: href(T, 'players', Y),
    value: href(T, 'value'), lab: href(T, 'lab', Y), model: '#/methodology' };
}
function updateHeader() {
  const T = state.tour, Y = state.year;
  document.querySelectorAll('.ta-tour button[data-tour]').forEach(b => b.setAttribute('aria-pressed', b.dataset.tour === T ? 'true' : 'false'));
  const links = sectionHrefs(T, Y);
  document.querySelectorAll('.qk-secnav a[data-sec]').forEach(a => { if (links[a.dataset.sec]) a.setAttribute('href', links[a.dataset.sec]); });
  if (document.body) TOURS.forEach(t => document.body.classList.toggle('tour-' + t, t === T));
}
function markNav(key) { if (SHELL) SHELL.setSection(key); }
function setMeta(html) {
  const el = document.getElementById('meta-line');
  if (!el) return;
  const d = INDEX.data;
  const base = d && d.updated_at ? 'Updated ' + esc(fmtStamp(d.updated_at)) : '';
  el.innerHTML = [html, base].filter(Boolean).join(' · ');
}

function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
const SEARCH = {};
/* The search palette's rows: the tour's players (players_index.json) and this year's tournaments. */
function loadSearch() {
  const T = state.tour, Y = state.year || currentYear(T);
  const key = T + '/' + Y;
  if (SEARCH[key]) return SEARCH[key];
  SEARCH[key] = ensureTour(T, Y).then(() => {
    const items = [];
    const P = NAMES[T];
    Object.keys(P).forEach(id => {
      const x = P[id] || {};
      if (!x.name) return;
      items.push({ sport: 'tennis', t: x.name, s: [TOUR_NAME[T], x.country, isNum(x.rank) ? 'No. ' + x.rank : ''].filter(Boolean).join(' · '), href: playerHref(T, id), order: isNum(x.rank) ? Number(x.rank) : 100000 });
    });
    const ev = EVENTS[T][String(Y)] || {};
    Object.keys(ev).forEach(id => {
      const e = ev[id] || {};
      if (e.level === 'q') return;
      items.push({ sport: 'tennis', t: (e.name || eventName(T, id)) + ' ' + Y, s: [levelLabel(e.level, T), surfaceLabel(e.surface, e.indoor), e.city].filter(Boolean).join(' · '),
        href: eventHref(T, id), order: 500 + levelRank(e.level) });
    });
    items.sort((a, b) => a.order - b.order);
    return items;
  });
  return SEARCH[key];
}
function closeSearch() { /* the palette closes itself on navigation */ }
function initHeader() {
  const sel = document.getElementById('year-select');
  if (sel) sel.addEventListener('change', () => setYear(sel.value));
  document.querySelectorAll('.ta-tour button[data-tour]').forEach(b => b.addEventListener('click', () => switchTour(b.dataset.tour)));
}
function liveAny() { const d = INDEX.data || {}; return TOURS.some(t => (((d.tours || {})[t] || {}).live || []).length > 0); }
function init() {
  if (window.QK) {
    SHELL = QK.shell({
      sport: 'tennis', section: 'overview',
      sections: QK.sections('tennis', { value: 'Value', fantasy: null }).map(x => Object.assign({}, x, { href: x.key === 'overview' ? '#/' : '#/' + x.key })),
      ctx: ctxHTML(),
      search: { load: loadSearch }
    });
  }
  load('index.json').then(idx => {
    INDEX.data = idx;
    initHeader();
    if (SHELL) SHELL.setLive({ tennis: liveAny() });
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
  ROUTES: ROUTES, HANDLERS: HANDLERS, TITLES: TITLES, TOURS: TOURS, TOUR_NAME: TOUR_NAME,
  switchTour: switchTour, setYear: setYear, setMeta: setMeta,
  // data
  load: load, loadAll: loadAll, ok: ok, reason: reason, cached: cached, tpath: tpath, ypath: ypath,
  eventPath: eventPath, matchPath: matchPath, playerPath: playerPath, loadTour: loadTour, loadYear: loadYear, ensureTour: ensureTour,
  index: () => INDEX.data, tourInfo: tourInfo, currentYear: currentYear, years: years, tourName: tourName, isTour: isTour, yearOfId: yearOfId,
  NAMES: NAMES, EVENTS: EVENTS,
  // formatting
  esc: esc, num: num, pct: pct, signed: signed, pp: pp, fmtSec: fmtSec, fmtDuration: fmtDuration, fmtDate: fmtDate, fmtTime: fmtTime,
  fmtStamp: fmtStamp, fmtRange: fmtRange, localDay: localDay, todayISO: todayISO, countdown: countdown, ordinal: ordinal, fmtVal: fmtVal,
  metric: metric, record: record, american: american, decimal: decimal, devig2: devig2, sourceNames: sourceNames, parseDate: parseDate, isNum: isNum, titleCase: titleCase,
  // tennis
  SURFACES: SURFACES, LEVELS: LEVELS, ROUND_ORDER: ROUND_ORDER, MAIN_ROUNDS: MAIN_ROUNDS,
  surfaceColour: surfaceColour, surfaceLabel: surfaceLabel, surfaceDot: surfaceDot, surfaceChip: surfaceChip,
  levelLabel: levelLabel, levelShort: levelShort, levelChip: levelChip, levelRank: levelRank, roundLabel: roundLabel, roundIndex: roundIndex,
  matchState: matchState, isFinished: isFinished, fmtScore: fmtScore, setsWon: setsWon, totalGames: totalGames, statusChip: statusChip,
  matchCard: matchCard, kitGame: kitGame, fresh: fresh, titleProbs: titleProbs, awardValue: awardValue, playersOf: playersOf, eventsOf: eventsOf,
  // names and links
  player: player, playerName: playerName, playerShort: playerShort, playerSurname: playerSurname, playerCountry: playerCountry,
  playerRank: playerRank, playerColour: playerColour, playerLink: playerLink, playerHref: playerHref,
  eventInfo: eventInfo, eventName: eventName, eventLink: eventLink, eventHref: eventHref, matchLink: matchLink, matchHref: matchHref,
  h2hHref: h2hHref, compareHref: compareHref, href: href, yq: yq,
  // HTML
  card: card, muted: muted, chip: chip, notBuilt: notBuilt, tableHTML: tableHTML, sortable: sortable, pctPill: pctPill, pctColor: pctColor,
  pctRow: pctRow, statTile: statTile, probCell: probCell, edgeHTML: edgeHTML, splitBar: splitBar, divColour: divColour, seqColour: seqColour,
  toggles: toggles, wireToggles: wireToggles, pageHead: pageHead, pctInk: pctInk, alpha: alpha, playerObj: playerObj,
  SECTION_OF: SECTION_OF, SECTION_TABS: SECTION_TABS, shell: () => SHELL, liveAny: liveAny,
  // charts
  PALETTE: PALETTE, C: C,
  FOOTBALL_URL: FOOTBALL_URL, PADDOCK_URL: PADDOCK_URL, HARDWOOD_URL: HARDWOOD_URL, BULLPEN_URL: BULLPEN_URL, GRIDIRON_URL: GRIDIRON_URL, RINK_URL: RINK_URL,
  charts: {}
};
})();
