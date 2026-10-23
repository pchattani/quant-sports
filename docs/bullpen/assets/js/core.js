/* The Quant Bullpen — core: namespace, state, routing, cached loading, helpers, search, and the
 * shell from The Quant design kit (assets/qk: QK.shell top bar, the nine-section nav, search palette,
 * theme; charts through the kit module assets/qk/plotly-ec.js on ECharts).
 *
 * Sections (docs/REDESIGN.md), each a group of routes with its own tab strip (SECTION_TABS below):
 *   Overview #/<L> · Games (scoreboard, game centre, odds board) · Standings (standings, postseason,
 *   awards, history) · Teams · Players (hitters, pitchers, leaderboards, prospects, player pages) ·
 *   Value & Moves (value, trade simulator, moves) · Fantasy · Lab (scatter lab, compare, parks,
 *   umpires) · Model (methodology, calibration, glossary, terms). Every old route still resolves.
 *
 * A static shell over JSON payloads under data/ (see oddsmarkets/baseball/PAYLOADS.md).
 * Every page module registers itself with BP.route(name, renderFn) and never edits this
 * file. Routes (hash); L is the level, 'mlb', 'aaa' or 'npb', and may prefix any route. The npb level's pages
 * live in npb.js and register with BP.routeNpb(name, fn): while the level is npb they take over the route name:
 *
 *   #/  #/<L>                          hub (level = last viewed, default mlb)
 *   #/<L>/games[/<date>]               games of a day (YYYY-MM-DD)
 *   #/<L>/game/<gpk>                   game centre
 *   #/<L>/standings                    standings
 *   #/<L>/hitters  #/<L>/pitchers      catalogues
 *   #/<L>/hitter/<pid>  #/<L>/pitcher/<pid>  #/player/<pid>   player pages
 *   #/<L>/teams  #/<L>/team/<tid>      teams
 *   #/<L>/leaders  #/<L>/lab           leaderboards, lab
 *   #/<L>/value  #/<L>/trade           player value and the best at each position; the trade simulator
 *   #/postseason  #/markets  #/umpires  #/umpire/<id>  #/parks  #/park/<vid>  #/prospects
 *   #/history  #/awards  #/compare[/<a>[/<b>]]  #/calibration  #/glossary[/<key>]  #/methodology  #/disclaimer
 *
 * Season: every page reads BP.state.season. It comes from a "?s=<YYYY>" query (any page),
 * else the level's current season (index.json levels[L].season, else index.json season).
 * Links built with the helpers below carry ?s= when the season shown is not the current one.
 *
 * Before a page renders, core loads players_index.json (names for every pid), so
 * BP.playerName / BP.playerLink work synchronously. Team names come from index.json "teams"
 * (and any payload carrying a "teams" dict), with a built-in MLB table as the fallback.
 *
 * A render function is called as fn(el, params, state): `el` is a fresh <div> inside
 * <main id="app"> (detached when the viewer navigates away, so async code can test
 * el.isConnected); `params` holds {level, season, id, a, b, date, rest, query}. It may return a Promise.
 *
 * Helpers that take a level take it LAST and optionally (playerHref(pid, opts), teamLink(tid, opts),
 * gameHref(gpk, L, S)); the current level and season are used when they are left out.
 */
window.BP = (function () {
'use strict';

// ── constants ──────────────────────────────────────────────────────────────

/* Colours are design tokens (CSS custom properties): HTML uses them directly, the chart shim resolves them
 * for the current theme at paint time. Model = chart slot 1 (blue), market = slot 2 (orange), on every site. */
const C = {
  bg: 'var(--bg)', bg2: 'var(--s-1)', bg3: 'var(--s-2)', border: 'var(--line-2)',
  text: 'var(--ink-1)', text2: 'var(--ink-2)', text3: 'var(--ink-3)',
  blue: 'var(--c-1)', green: 'var(--up)', red: 'var(--down)', orange: 'var(--c-2)',
  purple: 'var(--c-7)', yellow: 'var(--c-4)', teal: 'var(--c-3)',
  clay: 'var(--signal)', clay2: 'var(--signal)', navy: 'var(--s-3)', navy2: 'var(--s-3)',
  bp: 'var(--signal)', p1: 'var(--signal)', p2: 'var(--c-2)', home: 'var(--c-1)', away: 'var(--c-2)',
  espn: 'var(--ink-3)', market: 'var(--c-market)', model: 'var(--signal)', accent: 'var(--signal)'
};
const PALETTE = ['var(--c-1)', 'var(--c-2)', 'var(--c-3)', 'var(--c-4)', 'var(--c-5)', 'var(--c-6)', 'var(--c-7)', 'var(--c-8)'];
/* A colour at alpha a: hex -> rgba(); a token or any CSS colour -> color-mix() (resolved by the browser or the chart shim). */
function alpha(c, a) {
  const h = String(c || '').replace('#', '');
  if (/^[0-9a-f]{6}$/i.test(h)) return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
  return 'color-mix(in srgb, ' + (c || 'var(--ink-3)') + ' ' + Math.round(a * 100) + '%, transparent)';
}
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
const GRIDIRON_URL = 'https://pchattani.github.io/the-quant-gridiron/';
const RINK_URL = 'https://pchattani.github.io/the-quant-rink/';
const SITE = 'The Quant Bullpen';
const LEVELS = ['mlb', 'aaa'];   // NPB taken off the public site 15 Oct 2026 (npb.jp terms); its code stays in the repo
const LEVEL_NAME = { mlb: 'MLB', aaa: 'AAA', npb: 'NPB' };
const LEVEL_LONG = { mlb: 'Major League Baseball', aaa: 'Triple-A', npb: 'Nippon Professional Baseball' };
const LS_LEVEL = 'qb-level';

/* MLB teams (MLBAM ids) as in the 2026 store: the fallback until index.json "teams" loads. [abbr, name, short, league, division, colour, venue] */
const MLB_TEAMS = {
  108: ['LAA', 'Los Angeles Angels', 'Angels', 'AL', 'AL West', '#ba0021', '1'],
  109: ['AZ', 'Arizona Diamondbacks', 'D-backs', 'NL', 'NL West', '#aa182c', '15'],
  110: ['BAL', 'Baltimore Orioles', 'Orioles', 'AL', 'AL East', '#df4601', '2'],
  111: ['BOS', 'Boston Red Sox', 'Red Sox', 'AL', 'AL East', '#0d2b56', '3'],
  112: ['CHC', 'Chicago Cubs', 'Cubs', 'NL', 'NL Central', '#0e3386', '17'],
  113: ['CIN', 'Cincinnati Reds', 'Reds', 'NL', 'NL Central', '#c6011f', '2602'],
  114: ['CLE', 'Cleveland Guardians', 'Guardians', 'AL', 'AL Central', '#002b5c', '5'],
  115: ['COL', 'Colorado Rockies', 'Rockies', 'NL', 'NL West', '#33006f', '19'],
  116: ['DET', 'Detroit Tigers', 'Tigers', 'AL', 'AL Central', '#0a2240', '2394'],
  117: ['HOU', 'Houston Astros', 'Astros', 'AL', 'AL West', '#002d62', '2392'],
  118: ['KC', 'Kansas City Royals', 'Royals', 'AL', 'AL Central', '#004687', '7'],
  119: ['LAD', 'Los Angeles Dodgers', 'Dodgers', 'NL', 'NL West', '#005a9c', '22'],
  120: ['WSH', 'Washington Nationals', 'Nationals', 'NL', 'NL East', '#ab0003', '3309'],
  121: ['NYM', 'New York Mets', 'Mets', 'NL', 'NL East', '#002d72', '3289'],
  133: ['ATH', 'Athletics', 'Athletics', 'AL', 'AL West', '#003831', '2529'],
  134: ['PIT', 'Pittsburgh Pirates', 'Pirates', 'NL', 'NL Central', '#27251f', '31'],
  135: ['SD', 'San Diego Padres', 'Padres', 'NL', 'NL West', '#2f241d', '2680'],
  136: ['SEA', 'Seattle Mariners', 'Mariners', 'AL', 'AL West', '#005c5c', '680'],
  137: ['SF', 'San Francisco Giants', 'Giants', 'NL', 'NL West', '#fd5a1e', '2395'],
  138: ['STL', 'St. Louis Cardinals', 'Cardinals', 'NL', 'NL Central', '#be0a14', '2889'],
  139: ['TB', 'Tampa Bay Rays', 'Rays', 'AL', 'AL East', '#092c5c', '12'],
  140: ['TEX', 'Texas Rangers', 'Rangers', 'AL', 'AL West', '#003278', '5325'],
  141: ['TOR', 'Toronto Blue Jays', 'Blue Jays', 'AL', 'AL East', '#134a8e', '14'],
  142: ['MIN', 'Minnesota Twins', 'Twins', 'AL', 'AL Central', '#031f40', '3312'],
  143: ['PHI', 'Philadelphia Phillies', 'Phillies', 'NL', 'NL East', '#e81828', '2681'],
  144: ['ATL', 'Atlanta Braves', 'Braves', 'NL', 'NL East', '#0c2340', '4705'],
  145: ['CWS', 'Chicago White Sox', 'White Sox', 'AL', 'AL Central', '#27251f', '4'],
  146: ['MIA', 'Miami Marlins', 'Marlins', 'NL', 'NL East', '#00a3e0', '4169'],
  147: ['NYY', 'New York Yankees', 'Yankees', 'AL', 'AL East', '#132448', '3313'],
  158: ['MIL', 'Milwaukee Brewers', 'Brewers', 'NL', 'NL Central', '#13294b', '32']
};
const DIVISIONS = ['AL East', 'AL Central', 'AL West', 'NL East', 'NL Central', 'NL West'];

/* Statcast pitch types: names and the colours every chart uses. */
const PITCH_NAMES = {
  FF: 'Four-seam', SI: 'Sinker', FC: 'Cutter', FT: 'Two-seam', SL: 'Slider', ST: 'Sweeper', SV: 'Slurve', CU: 'Curveball',
  KC: 'Knuckle curve', CS: 'Slow curve', CH: 'Changeup', FS: 'Splitter', FO: 'Forkball', SC: 'Screwball', KN: 'Knuckleball',
  EP: 'Eephus', FA: 'Fastball', PO: 'Pitchout', IN: 'Intentional ball', UN: 'Unknown', AB: 'Automatic ball', AS: 'Automatic strike'
};
/* Kit v3 (Matchday): the Savant families (fastballs red-orange, cutters brown, sliders yellow, curves blue, changeups
   green, splitters cyan) on the warm dark palette; blue stays "ours", so no pitch type uses it. */
const PITCH_COLOURS = {
  FF: '#ef6a4c', FA: '#ef6a4c', SI: '#f39a3d', FT: '#f39a3d', FC: '#b97d4e', SL: '#ffc94d', ST: '#e0b04a', SV: '#94cf7c',
  CU: '#62aef0', KC: '#a08cf0', CS: '#7da7dc', CH: '#5cc183', FS: '#58c5d8', FO: '#86d6c0', SC: '#a9dc7a', KN: '#cbbfa9',
  EP: '#b9ae9c', PO: '#8a8070', IN: '#8a8070', UN: '#8a8070'
};
const PITCH_ORDER = ['FF', 'FA', 'SI', 'FT', 'FC', 'SL', 'ST', 'SV', 'CU', 'KC', 'CS', 'CH', 'FS', 'FO', 'SC', 'KN', 'EP'];
/* Pitch result -> [label, colour, kind]; kind: ball | called | swinging | foul | inplay | hbp. */
const CALLS = {
  ball: ['Ball', '#62aef0', 'ball'], blocked_ball: ['Ball (blocked)', '#62aef0', 'ball'], intent_ball: ['Intentional ball', '#62aef0', 'ball'],
  pitchout: ['Pitchout', '#62aef0', 'ball'], automatic_ball: ['Automatic ball', '#62aef0', 'ball'],
  called_strike: ['Called strike', '#ef6a4c', 'called'], automatic_strike: ['Automatic strike', '#ef6a4c', 'called'],
  swinging_strike: ['Swinging strike', '#f39a3d', 'swinging'], swinging_strike_blocked: ['Swinging strike', '#f39a3d', 'swinging'],
  missed_bunt: ['Missed bunt', '#f39a3d', 'swinging'], foul_tip: ['Foul tip', '#f39a3d', 'swinging'],
  foul: ['Foul', '#ffc94d', 'foul'], foul_bunt: ['Foul bunt', '#ffc94d', 'foul'], bunt_foul_tip: ['Foul bunt', '#ffc94d', 'foul'],
  hit_into_play: ['In play', '#5cc183', 'inplay'], hit_into_play_no_out: ['In play', '#5cc183', 'inplay'], hit_into_play_score: ['In play', '#5cc183', 'inplay'],
  hit_by_pitch: ['Hit by pitch', '#a08cf0', 'hbp'],
  B: ['Ball', '#62aef0', 'ball'], S: ['Strike', '#ef6a4c', 'called'], X: ['In play', '#5cc183', 'inplay'], C: ['Called strike', '#ef6a4c', 'called']
};
const ROUND_LONG = { F: 'Wild Card Series', WC: 'Wild Card Series', D: 'Division Series', DS: 'Division Series', L: 'League Championship Series',
  LCS: 'League Championship Series', CS: 'League Championship Series', W: 'World Series', WS: 'World Series', R: 'Regular season', S: 'Spring training', E: 'Exhibition', A: 'All-Star Game',
  C: 'Triple-A National Championship' };
const ROUND_SHORT = { F: 'WC', WC: 'WC', D: 'DS', DS: 'DS', L: 'LCS', LCS: 'LCS', CS: 'LCS', W: 'WS', WS: 'WS', R: 'Reg', S: 'ST', E: 'Exh', A: 'ASG', C: 'Champ' };
const ROUND_KEY = { F: 'WC', WC: 'WC', D: 'DS', DS: 'DS', L: 'LCS', LCS: 'LCS', CS: 'LCS', W: 'WS', WS: 'WS' };

// ── state and registries ───────────────────────────────────────────────────

const state = { level: 'mlb', season: null, route: null, params: {}, hash: '' };
const INDEX = { data: null };
const NAMES = {};      // pid -> {name, short, team, pos, bats, throws, levels}
const TEAMS = {};      // tid -> {name, abbr, short, league, division, colour, venue, level, parent, placeholder}
const UMPS = {};       // id -> {name}
const VENUES = {};     // vid -> {name, city, dims, roof, elev_ft, ...}
const CACHE = {}, PENDING = {};
const HANDLERS = {};
const NPB_HANDLERS = {};   // the npb level's pages (npb.js)
let NPB_FALLBACK = null;   // the npb page for routes the level does not have
let CLEANUPS = [];

Object.keys(MLB_TEAMS).forEach(t => {
  const r = MLB_TEAMS[t];
  TEAMS[t] = { abbr: r[0], name: r[1], short: r[2], league: r[3], division: r[4], colour: r[5], venue: r[6], level: 'mlb' };
});

try { const l = window.localStorage.getItem(LS_LEVEL); if (LEVELS.indexOf(l) >= 0) state.level = l; } catch (e) { /* private mode */ }

function isLevel(x) { return LEVELS.indexOf(String(x)) >= 0; }

const ROUTES = [];
function addRoute(pattern, name, global) {
  ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, global: !!global });
}
addRoute('', 'hub');
addRoute('games', 'games');
addRoute('games/:date', 'games');
addRoute('game/:id', 'game');
addRoute('standings', 'standings');
addRoute('postseason', 'postseason', true);
addRoute('hitters', 'hitters');
addRoute('pitchers', 'pitchers');
addRoute('hitter/:id', 'hitter');
addRoute('pitcher/:id', 'pitcher');
addRoute('player/:id', 'player');
addRoute('teams', 'teams');
addRoute('team/:id', 'team');
addRoute('leaders', 'leaders');
addRoute('umpires', 'umpires', true);
addRoute('umpire/:id', 'umpire', true);
addRoute('parks', 'parks', true);
addRoute('park/:id', 'park', true);
addRoute('prospects', 'prospects', true);
addRoute('history', 'history', true);
addRoute('awards', 'awards', true);
addRoute('lab', 'lab');
addRoute('value', 'value');
addRoute('trade', 'trade');
addRoute('moves', 'moves');
addRoute('fantasy', 'fantasy');
addRoute('compare', 'compare', true);
addRoute('compare/:a', 'compare', true);
addRoute('compare/:a/:b', 'compare', true);
addRoute('markets', 'markets', true);
addRoute('calibration', 'calibration', true);
addRoute('glossary', 'glossary', true);
addRoute('glossary/:id', 'glossary', true);
addRoute('methodology', 'methodology', true);
addRoute('disclaimer', 'disclaimer', true);

const ALIASES = { home: 'hub', index: 'hub', '': 'hub', overview: 'hub', schedule: 'games', scores: 'games', fixtures: 'games', playoffs: 'postseason', docs: 'methodology',
  leaderboards: 'leaders', umpire_scorecards: 'umpires', ballparks: 'parks', players: 'hitters', model: 'methodology', odds: 'markets', terms: 'disclaimer' };
const TITLES = {
  hub: 'Overview', games: 'Games', game: 'Game centre', standings: 'Standings', postseason: 'Postseason', hitters: 'Hitters', pitchers: 'Pitchers',
  hitter: 'Hitter', pitcher: 'Pitcher', player: 'Player', teams: 'Teams', team: 'Team', leaders: 'Leaders', umpires: 'Umpires', umpire: 'Umpire',
  parks: 'Parks', park: 'Park', prospects: 'Prospects', history: 'History', awards: 'Awards', lab: 'Lab', compare: 'Compare', value: 'Value', trade: 'Trade simulator', moves: 'Moves', fantasy: 'Fantasy',
  markets: 'Forecast board', calibration: 'Calibration', glossary: 'Glossary', methodology: 'Methodology', disclaimer: 'Disclaimer & terms'
};
/* The nine sections (QK.sections('baseball')) and the routes each one holds. */
const SECTION_OF = { hub: 'overview', games: 'fixtures', game: 'fixtures', markets: 'fixtures', standings: 'standings', postseason: 'standings', awards: 'standings',
  history: 'standings', teams: 'teams', team: 'teams', hitters: 'players', pitchers: 'players', hitter: 'players', pitcher: 'players', player: 'players',
  leaders: 'players', prospects: 'players', value: 'value', trade: 'value', moves: 'value', fantasy: 'fantasy', lab: 'lab', compare: 'lab', parks: 'lab',
  park: 'lab', umpires: 'lab', umpire: 'lab', methodology: 'model', calibration: 'model', glossary: 'model', disclaimer: 'model' };
/* Tabs per section: [route, label, scope] with scope 'g' (a global route), 'mlb' (MLB only) or '' (per level). */
const SECTION_TABS = {
  fixtures: [['games', 'Scoreboard', ''], ['markets', 'Forecast board', 'g']],
  standings: [['standings', 'Standings', ''], ['postseason', 'Postseason', 'g'], ['awards', 'Award races', 'g'], ['history', 'All-time', 'g']],
  teams: [['teams', 'All teams', '']],
  players: [['hitters', 'Hitters', ''], ['pitchers', 'Pitchers', ''], ['leaders', 'Leaderboards', ''], ['prospects', 'Prospects', 'g']],
  value: [['value', 'Player value', ''], ['trade', 'Trade simulator', 'mlb'], ['moves', 'Moves & trades', 'mlb']],
  fantasy: [['fantasy', 'Fantasy baseball', 'mlb']],
  lab: [['lab', 'Scatter lab', ''], ['compare', 'Compare', 'g'], ['parks', 'Parks', 'g'], ['umpires', 'Umpires', 'g']],
  model: [['methodology', 'Methodology', 'g'], ['calibration', 'Calibration', 'g'], ['glossary', 'Glossary', 'g'], ['disclaimer', 'Terms', 'g']]
};
const SECTION_LABEL = { overview: 'Overview', fixtures: 'Games', standings: 'Standings', teams: 'Teams', players: 'Players', value: 'Value & Moves', fantasy: 'Fantasy', lab: 'Lab', model: 'Model' };
const SECTION_BLURB = {
  fixtures: 'Every game, by the numbers: our win chance from a plate-appearance simulation with the lineups and starters, live while games are on.',
  standings: 'Divisions, wild cards, the postseason bracket and title chances from the season simulation.',
  teams: 'Ratings, rosters, schedules, strengths and needs for every club.',
  players: 'Percentiles against each player\'s position or role, expected stats, arsenals and projections.',
  value: 'What every player is worth now and over the next five seasons, trades rated and simulated.',
  fantasy: 'Rotisserie and points rankings, dynasty values, picks, closers, steals and the weekly streamers.',
  lab: 'Build your own charts: any two metrics, head-to-head comparisons, parks and umpires.',
  model: 'How the models work, how well they have done, and every metric defined.'
};
/* Detail pages: the list they belong to (the back link in the section bar). */
const DETAIL_OF = { game: 'games', team: 'teams', hitter: 'hitters', pitcher: 'pitchers', player: 'hitters', park: 'parks', umpire: 'umpires' };
const NAV_OF = { hub: 'hub', games: 'games', game: 'games', standings: 'standings', postseason: 'postseason', hitters: 'hitters', hitter: 'hitters',
  pitchers: 'pitchers', pitcher: 'pitchers', player: 'hitters', teams: 'teams', team: 'teams', leaders: 'leaders', umpires: 'umpires', umpire: 'umpires',
  parks: 'parks', park: 'parks', prospects: 'prospects', history: 'history', awards: 'awards', lab: 'lab', compare: 'compare', value: 'value', trade: 'trade', moves: 'moves', fantasy: 'fantasy', markets: 'markets',
  calibration: 'calibration', glossary: 'glossary', methodology: 'methodology' };
// Where a page lands when the level is switched (id pages fall back to their list).
const SWITCH_TO = { game: 'games', hitter: 'hitters', pitcher: 'pitchers', player: 'hitters', team: 'teams' };

function normPattern(s) {
  let p = String(s || '').trim().replace(/^#/, '').replace(/^\/+|\/+$/g, '').replace(/<(\w+)>/g, ':$1');
  p = p.replace(/^(:L|:level|mlb|aaa|npb)(\/|$)/, '');
  return p;
}
function shape(p) { return p.split('/').map(s => (s.charAt(0) === ':' ? ':' : s)).join('/'); }

/* Register a page renderer: a route name ('game'), an alias, or a pattern ('#/<L>/game/<id>'). */
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
/* Register an npb page: used for the route name while the level is npb. name '*' sets the fallback. */
function routeNpb(name, fn) {
  if (typeof fn !== 'function') return;
  if (name === '*') NPB_FALLBACK = fn; else NPB_HANDLERS[name] = fn;
  if (booted && state.level === 'npb' && (state.route === name || name === '*')) render();
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
  let parts = h.split('/').filter(s => s !== '').map(s => { try { return decodeURIComponent(s); } catch (e) { return s; } });
  let level = null;
  if (parts.length && isLevel(parts[0].toLowerCase())) { level = parts[0].toLowerCase(); parts = parts.slice(1); }
  if (parts.length && ALIASES[parts[0]] && ALIASES[parts[0]] !== 'hub') parts[0] = ALIASES[parts[0]];
  let best = null, bestLen = -1;
  ROUTES.forEach(r => {
    if (r.segs.length > parts.length) return;
    if (r.segs.length === 0 && parts.length > 0) return;
    for (let i = 0; i < r.segs.length; i++) if (r.segs[i].charAt(0) !== ':' && r.segs[i] !== parts[i]) return;
    const score = r.segs.length * 2 + (r.segs.length === parts.length ? 1 : 0);
    if (score > bestLen) { best = r; bestLen = score; }
  });
  const params = { level: level, rest: [], query: query };
  if (!best) return { name: 'notfound', params: Object.assign(params, { rest: parts }), parts: parts, level: level };
  best.segs.forEach((s, i) => { if (s.charAt(0) === ':') params[s.slice(1)] = parts[i]; });
  params.rest = parts.slice(best.segs.length);
  const s = query.s || query.season || query.y;
  const y = s ? parseInt(s, 10) : NaN;
  params.season = isNaN(y) ? undefined : y;
  return { name: best.name, params: params, parts: parts, level: level, global: best.global };
}

function handlerFor(name) {
  if (state.level === 'npb' && name !== 'notfound') {
    if (NPB_HANDLERS[name]) return NPB_HANDLERS[name];
    if (name === 'hitter' || name === 'pitcher') return NPB_HANDLERS.player || null;
    if (['glossary', 'methodology', 'disclaimer'].indexOf(name) < 0 && NPB_FALLBACK) return NPB_FALLBACK;
  }
  if (HANDLERS[name]) return HANDLERS[name];
  // a player page served by the other role's renderer, or the combined one
  if (name === 'hitter' || name === 'pitcher') return HANDLERS.player || HANDLERS[name === 'hitter' ? 'pitcher' : 'hitter'] || null;
  if (name === 'player') return HANDLERS.hitter || HANDLERS.pitcher || null;
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
  runCleanups();
  closeSearch();
  setRecords({}); setForms({});
  const r = parseHash();
  const prevLevel = state.level, prevSeason = state.season;
  if (r.level) setLevelState(r.level);
  r.params.level = state.level;
  const S = r.params.season || currentSeason(state.level);
  r.params.season = S;
  state.season = S;
  state.route = r.name;
  state.params = r.params;
  state.hash = location.hash || '#/';
  if (prevLevel !== state.level || prevSeason !== state.season || !pickerFilled) fillSeasonPicker();
  updateHeader();
  markNav(SECTION_OF[r.name] || '');
  const app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '';
  app.appendChild(sectionBar(r));
  const el = document.createElement('div');
  el.className = 'page page-' + r.name.replace(/[^a-z0-9-]/gi, '-') + ' level-' + state.level;
  app.appendChild(el);
  document.title = (r.name === 'hub' ? LEVEL_NAME[state.level] + ' ' + (state.season || '') + ' · ' : (TITLES[r.name] || 'Page') + (r.global ? '' : ' · ' + LEVEL_NAME[state.level]) + ' · ') + SITE;
  setMeta('');
  if (!keep) window.scrollTo(0, 0);
  const fn = handlerFor(r.name);
  if (!fn) {
    el.innerHTML = r.name === 'notfound'
      ? comingHTML('Page not found', 'There is no page at <code>' + esc(location.hash) + '</code>. Try the overview or the search (press /).')
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
      if (out && typeof out.then === 'function') out.then(() => { if (keep) window.scrollTo(0, y0); jumpNav(el, r); }, err => showError(el, err));
      else { if (keep) window.scrollTo(0, y0); jumpNav(el, r); }
    } catch (err) { showError(el, err); }
  });
}

function comingHTML(title, body) {
  return '<div class="qk-card coming"><div class="qk-card-body"><div class="coming-title">' + esc(title) + '</div>' +
    '<p class="muted-inline">' + body + '</p><p><a class="qk-link" href="#/' + state.level + '">Back to the overview</a></p></div></div>';
}
/* Long detail pages (team, player) get a sticky "on this page" strip of their card titles. */
const JUMP_PAGES = ['team', 'hitter', 'pitcher', 'player'];
function jumpNav(el, r) {
  if (JUMP_PAGES.indexOf(r.name) < 0) return;
  const build = () => {
    if (!el.isConnected) return;
    const heads = Array.prototype.slice.call(el.querySelectorAll('.card > .card-header, .qk-card > .qk-card-head')).filter(h => h.offsetParent);
    let nav = el.parentNode.querySelector('.bp-jump');
    if (heads.length < 4) { if (nav) nav.remove(); return; }
    if (!nav) { nav = document.createElement('nav'); nav.className = 'bp-jump'; nav.setAttribute('aria-label', 'On this page'); el.parentNode.insertBefore(nav, el); }
    const label = h => { const t = h.querySelector('.qk-card-title'); const raw = t ? t.textContent : (h.childNodes[0] ? h.childNodes[0].textContent : h.textContent); return String(raw || '').trim().slice(0, 34); };
    nav.innerHTML = '<div class="qk-chips scroll">' + heads.map((h, i) => '<button type="button" class="qk-chip" data-i="' + i + '">' + esc(label(h)) + '</button>').join('') + '</div>';
    nav.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      const c = heads[+b.dataset.i].closest('.card, .qk-card') || heads[+b.dataset.i];
      const off = ['.qk-topbar', '.qk-secnav'].reduce((a, q) => a + ((document.querySelector(q) || {}).offsetHeight || 0), 0) + nav.offsetHeight + 12;
      window.scrollTo({ top: c.getBoundingClientRect().top + window.scrollY - off, behavior: QK && QK.reducedMotion && QK.reducedMotion() ? 'auto' : 'smooth' });
    }));
  };
  setTimeout(build, 350);
  setTimeout(build, 1500);
  el.addEventListener('click', e => { if (e.target.closest && e.target.closest('.seg-tabs a, .tbtn, [role="tab"]')) setTimeout(build, 250); });
}
/* The bar above every page: section kicker and title, the section's tabs; on a detail page a link back to its list. */
function tabHref(t, L) {
  return t[2] === 'g' ? ghref(t[0]) : t[2] === 'mlb' ? '#/mlb/' + t[0] : href(t[0], L);
}
function sectionBar(r) {
  const sec = SECTION_OF[r.name] || '';
  const bar = document.createElement('div');
  bar.className = 'bp-secbar';
  if (!sec || sec === 'overview' || r.name === 'notfound') { bar.hidden = true; bar.innerHTML = '<span id="meta-line" hidden></span>'; return bar; }
  const L = state.level, S = state.season;
  const tabs = SECTION_TABS[sec] || [];
  const detail = DETAIL_OF[r.name];
  const glob = (routeEntry(r.name) || {}).global;
  const kicker = (sec === 'model' ? SITE : glob && ['postseason', 'awards', 'markets', 'compare'].indexOf(r.name) < 0 ? SITE + ' · MLB and Triple-A' : LEVEL_LONG[L] + ' · ' + S);
  let back = '';
  if (detail) {
    const t = tabs.find(x => x[0] === detail) || [detail, TITLES[detail] || titleCase(detail), routeEntry(detail) && routeEntry(detail).global ? 'g' : ''];
    back = '<a class="bp-back" href="' + tabHref(t, L) + '"><span aria-hidden="true">←</span> ' + esc(SECTION_LABEL[sec] === t[1] ? t[1] : SECTION_LABEL[sec] + ' · ' + t[1]) + '</a>';
  }
  bar.classList.toggle('is-detail', !!detail);
  const head = detail ? '<div class="bp-sec-title"><div class="qk-kicker">' + esc(kicker) + '</div>' + back + '</div>'
    : (window.QK && QK.sectionHead ? QK.sectionHead({ kicker: kicker, title: SECTION_LABEL[sec], sub: SECTION_BLURB[sec] || '', size: 'lg', tag: 'h1', cls: 'bp-sh' })
      : '<div class="bp-sec-title"><div class="qk-kicker">' + esc(kicker) + '</div><h1>' + esc(SECTION_LABEL[sec]) + '</h1></div>');
  bar.innerHTML = '<div class="bp-secbar-in">' + head + '<div class="bp-meta" id="meta-line"></div></div>' +
    (tabs.length > 1 && !detail ? '<nav class="qk-tabs bp-tabs" aria-label="' + esc(SECTION_LABEL[sec]) + ' pages">' + tabs.map(t =>
      '<a class="qk-tab" href="' + tabHref(t, L) + '"' + (t[0] === r.name ? ' aria-selected="true" aria-current="page"' : ' aria-selected="false"') + '>' + esc(t[1]) +
      (t[2] === 'mlb' && L !== 'mlb' ? ' <span class="bp-tab-tag">MLB</span>' : '') + '</a>').join('') + '</nav>' : '');
  return bar;
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
 * missing or broken. A payload written with "ok": false resolves as written: test with BP.ok(d). */
/* Display-only metric labels: payload labels that read as betting words on this site (Statcast's "Edge%" is the shadow
   zone; the copy rules in docs/_design/STYLE_GUIDE.md keep "edge" out of labels). Applied to every catalogue and the glossary. */
const RELABEL = { edge_pct: ['Shadow%', 'Pitches in the shadow zone: the band just inside and just outside the border of the strike zone.'] };
/* per catalogue kind (ACCURACY_AUDIT.md: pitcher R is runs while on the mound; BB is unintentional walks; G counts games with a PA) */
const RELABEL_KIND = { pitcher: { r: ['R (on the mound)', 'Runs scored while the pitcher was on the mound: inherited runners are not reassigned to the pitcher who put them on, and these are not earned runs.'], bb: ['uBB', 'Unintentional walks.'] },
  hitter: { g: ['G (with a PA)', 'Games with a plate appearance (defensive replacements and pinch runners without a PA are not counted).'], bb: ['uBB', 'Unintentional walks.'] } };
function relabel(d) {
  if (!d || typeof d !== 'object') return;
  const K2 = RELABEL_KIND[d.kind] || null;
  const fix = m => { const r = m && (RELABEL[m.key] || (K2 && K2[m.key])); if (r) { m.label = r[0]; if (m.desc !== undefined) m.desc = r[1]; } };
  if (Array.isArray(d.metrics)) d.metrics.forEach(fix);
  else if (d.metrics && typeof d.metrics === 'object') Object.keys(d.metrics).forEach(kd => {   /* lab.json: {hitter: [...], pitcher: [...]} */
    const K3 = RELABEL_KIND[kd] || null;
    if (Array.isArray(d.metrics[kd])) d.metrics[kd].forEach(m => { const r = m && (RELABEL[m.key] || (K3 && K3[m.key])); if (r) { m.label = r[0]; if (m.desc !== undefined) m.desc = r[1]; } });
  });
  if (Array.isArray(d.groups)) d.groups.forEach(g => (g && Array.isArray(g.entries) ? g.entries.forEach(fix) : null));
}
function load(p0) {
  const p = String(p0).replace(/^\/+/, '').replace(/^data\//, '');
  if (Object.prototype.hasOwnProperty.call(CACHE, p)) return Promise.resolve(CACHE[p]);
  if (PENDING[p]) return PENDING[p];
  PENDING[p] = fetch('data/' + p, { cache: 'no-cache' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(d => { relabel(d); learn(p, d); return d; })
    .catch(err => { console.warn('payload missing:', p, err.message); return null; })
    .then(d => { if (d !== null) CACHE[p] = d; delete PENDING[p]; return d; });
  return PENDING[p];
}
function loadAll(paths) { return Promise.all(paths.map(load)); }
/* Forget cached payloads so the next load fetches them again (live refresh). */
function uncache(paths) { (Array.isArray(paths) ? paths : [paths]).forEach(p0 => { const p = String(p0).replace(/^\/+/, '').replace(/^data\//, ''); delete CACHE[p]; }); }
/* Re-fetch index.json (fresh live cards), then resolve with it. */
function refreshIndex() { uncache('index.json'); return load('index.json').then(d => { if (d) INDEX.data = d; if (SHELL) SHELL.setLive({ baseball: liveAny() }); return INDEX.data; }); }
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
/* Per-level payload path: lpath('calibration.json') -> 'mlb/calibration.json'. */
function lpath(file, L) { return (isLevel(L) ? L : state.level) + '/' + file; }
/* Per-level-season payload path: ypath('season.json') -> 'mlb/2026/season.json'. */
function ypath(file, L, S) {
  const l = isLevel(L) ? L : state.level;
  return l + '/' + (S || (l === state.level ? state.season : null) || currentSeason(l)) + '/' + file;
}
function gamePath(gpk, L, S) { return ypath('games/' + gpk + '.json', L, S); }
function playerPath(pid) { return 'players/' + pid + '.json'; }
function loadLevel(file, L) { return load(lpath(file, L)); }
function loadYear(file, L, S) { return load(ypath(file, L, S)); }
/* A game payload: the season given (or the current one), then the season before (game pages are kept for two). */
/* mlb/<S>/markets.json is built for the current season only: older seasons read nothing (index.json, already cached). */
function marketsPath(S) { return Number(S) === currentSeason('mlb') ? ypath('markets.json', 'mlb', S) : 'index.json'; }
function loadGame(gpk, L, S) {
  const l = isLevel(L) ? L : state.level;
  const s = Number(S || state.season || currentSeason(l));
  return load(gamePath(gpk, l, s)).then(d => (d ? d : load(gamePath(gpk, l, s - 1))));
}

/* players_index.json: resolves when it has loaded (or failed). */
let namesP = null;
function ensureNames() {
  if (!namesP) namesP = load('players_index.json');
  return namesP;
}

/* players_index.json comes flat ({pid: [...]}) per PAYLOADS.md, or wrapped ({"ok", ..., "players": {...}}): accept both. */
function playersOf(d) { return d && d.players && typeof d.players === 'object' && !Array.isArray(d.players) ? d.players : (d || {}); }

function putTeam(tid, x, L) {
  if (!tid || !x || typeof x !== 'object') return;
  const cur = TEAMS[tid] || {};
  const o = {};
  ['name', 'abbr', 'short', 'league', 'division', 'colour', 'venue', 'parent', 'city', 'placeholder', 'jp'].forEach(k => { if (x[k] !== undefined && x[k] !== null && x[k] !== '') o[k] = x[k]; });
  if (x.color && !o.colour) o.colour = x.color;
  if (L && !cur.level) o.level = L;
  TEAMS[tid] = Object.assign({}, cur, o);
}
function putPlayer(pid, info) { if (!pid || !info) return; NAMES[pid] = Object.assign({}, NAMES[pid] || {}, info); }
/* Harvest names, teams, umpires and venues from any payload that carries them. */
function learn(p, d) {
  if (!d || typeof d !== 'object') return;
  const lm = /^(mlb|aaa|npb)\//.exec(p);
  const L = lm ? lm[1] : null;
  try {
    if (p === 'players_index.json') {
      const P = playersOf(d);
      Object.keys(P).forEach(id => {
        const r = P[id];
        if (Array.isArray(r)) putPlayer(id, { name: r[0], team: r[1], pos: r[2], bats: r[3], throws: r[4], levels: r[5] });
        else if (r && typeof r === 'object' && r.name) putPlayer(id, r);
      });
    }
    if (p === 'index.json') {
      if (d.teams) Object.keys(d.teams).forEach(t => { if (/^\d+$/.test(t)) putTeam(t, d.teams[t], (d.teams[t] || {}).level || null); });
      if (d.levels) LEVELS.forEach(l => { const x = d.levels[l]; if (x && x.teams) Object.keys(x.teams).forEach(t => putTeam(t, x.teams[t], l)); });
    }
    if (d.teams && typeof d.teams === 'object' && !Array.isArray(d.teams) && p !== 'index.json') {
      Object.keys(d.teams).forEach(t => { const x = d.teams[t]; if (/^\d+$/.test(t) && x && (x.name || x.abbr)) putTeam(t, x, L); });
    }
    // a game page names its two teams under teams.home / teams.away (with their ids)
    if (d.teams && typeof d.teams === 'object' && !Array.isArray(d.teams)) ['home', 'away'].forEach(s => { const x = d.teams[s]; if (x && typeof x === 'object' && /^\d+$/.test(String(x.id || '')) && x.name) putTeam(String(x.id), x, d.level || L); });
    if (d.venues && typeof d.venues === 'object') Object.keys(d.venues).forEach(v => { VENUES[v] = Object.assign({}, VENUES[v] || {}, d.venues[v]); });
    if (d.parks && typeof d.parks === 'object' && !Array.isArray(d.parks)) Object.keys(d.parks).forEach(v => { const x = d.parks[v]; if (x && x.name) VENUES[v] = Object.assign({}, VENUES[v] || {}, x); });
    if (d.park && d.park.name) { const v = String(d.park.vid || d.park.id || d.venue || ''); if (v) VENUES[v] = Object.assign({}, VENUES[v] || {}, d.park); }
    if (d.umpires && typeof d.umpires === 'object' && !Array.isArray(d.umpires)) Object.keys(d.umpires).forEach(u => { const x = d.umpires[u]; if (x && x.name) UMPS[u] = Object.assign({}, UMPS[u] || {}, { name: x.name }); });
    if (d.umpire && typeof d.umpire === 'object' && d.umpire.id && d.umpire.name) UMPS[String(d.umpire.id)] = Object.assign({}, UMPS[String(d.umpire.id)] || {}, { name: d.umpire.name });
    if (d.names && typeof d.names === 'object' && !Array.isArray(d.names)) {
      Object.keys(d.names).forEach(id => { const n = d.names[id]; if (typeof n === 'string' && !(NAMES[id] || {}).name) putPlayer(id, { name: n }); });
    }
    if (/^players\/[^/]+\.json$/.test(p) && d.name) putPlayer(String(d.id || p.split('/').pop().replace('.json', '')), { name: d.name, pos: d.pos, bats: d.bats, throws: d.throws });
    if (d.players && typeof d.players === 'object' && !Array.isArray(d.players) && p !== 'players_index.json') {
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
/* A rate in the baseball style: .312 (avg, OBP, SLG, wOBA). */
function fmtAvg(v, d) {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 3 : d);
  return s.replace(/^0\./, '.').replace(/^-0\./, '-.');
}
/* Innings pitched from outs or decimal innings: fmtIP(6.333) -> "6.1"; fmtIP(19, true) -> "6.1". */
function fmtIP(v, outs) {
  if (!isNum(v)) return '—';
  const o = outs ? Math.round(Number(v)) : Math.round(Number(v) * 3);
  return Math.floor(o / 3) + '.' + (o % 3);
}
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
/* fmtDate("2026-10-03") -> "Sat 3 Oct 2026". opts {year:false, time:true, weekday:false}. A plain date is shown as written. */
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
/* Shift a YYYY-MM-DD by n days. */
function addDays(iso, n) {
  const d = parseDate(iso);
  if (!d) return iso;
  const t = new Date(d.getTime() + n * 86400000);
  return t.getUTCFullYear() + '-' + String(t.getUTCMonth() + 1).padStart(2, '0') + '-' + String(t.getUTCDate()).padStart(2, '0');
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
/* Format a catalogue value by its METRIC fmt (PAYLOADS.md): int|0|1|2|3|avg|pct|prob|signed|pm|plus|ip|mph|rpm|in|ft|deg.
 * pct and prob are fractions 0-1. "plus" scores are integers (100 = average). */
function fmtVal(v, fmt) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt)) {
    case 'pct': return (x * 100).toFixed(1) + '%';
    case 'prob': return pct(x);
    case 'int': case 'plus': return String(Math.round(x));
    case 'pm': return signed(x, 1);
    case 'signed': return signed(x, 2);
    case 'signed1': return signed(x, 1);
    case '0': return x.toFixed(0);
    case '1': return x.toFixed(1);
    case '3': case 'avg': return fmtAvg(x);
    case 'ip': return fmtIP(x);
    case 'mph': return x.toFixed(1);
    case 'rpm': return String(Math.round(x));
    case 'in': return x.toFixed(1);
    case 'ft': return x.toFixed(1);
    case 'deg': return x.toFixed(0) + '°';
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
/* A run line or spread point: 1.5 -> "+1.5", -1.5 -> "-1.5". */
function fmtLine(v) { return isNum(v) ? (Number(v) > 0 ? '+' : '') + Number(v).toFixed(1) : '—'; }
function titleCase(id) {
  return String(id || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

// ── baseball vocabulary ────────────────────────────────────────────────────

/* 'top' | 'bot' from 0/1, 'top'/'bottom', 'T'/'B', true (top). */
function halfOf(h) {
  if (h === true) return 'top';
  if (h === false) return 'bot';
  const s = String(h === null || h === undefined ? '' : h).toLowerCase();
  if (s === '0' || s === 't' || s.indexOf('top') === 0) return 'top';
  if (s === '1' || s === 'b' || s.indexOf('bot') === 0) return 'bot';
  return '';
}
/* inningLabel(3, 'top') -> "Top 3rd"; short -> "▲3". */
function inningLabel(inning, half, short) {
  if (!isNum(inning)) return '—';
  const h = halfOf(half);
  if (short) return (h === 'top' ? '▲' : h === 'bot' ? '▼' : '') + inning;
  return (h === 'top' ? 'Top ' : h === 'bot' ? 'Bot ' : '') + ordinal(inning);
}
function countText(b, s) { return isNum(b) && isNum(s) ? Number(b) + '-' + Number(s) : '—'; }
function outsText(o) { return isNum(o) ? Number(o) + (Number(o) === 1 ? ' out' : ' outs') : '—'; }
/* Bases as a bitmask (1 first, 2 second, 4 third), [on1, on2, on3] or "1_3" -> [b1, b2, b3] booleans. */
function basesOf(b) {
  if (Array.isArray(b)) return [!!b[0], !!b[1], !!b[2]];
  if (isNum(b)) { const n = Number(b); return [!!(n & 1), !!(n & 2), !!(n & 4)]; }
  const s = String(b || '');
  return [s.indexOf('1') >= 0, s.indexOf('2') >= 0, s.indexOf('3') >= 0];
}
/* A small diamond (SVG) with the runners on, and the outs as dots when given. */
function basesHTML(b, outs) {
  const on = basesOf(b);
  const sq = (cx, cy, f) => '<rect x="' + (cx - 3.5) + '" y="' + (cy - 3.5) + '" width="7" height="7" transform="rotate(45 ' + cx + ' ' + cy + ')" style="fill:' + (f ? 'var(--accent)' : 'none') + ';stroke:' + (f ? 'var(--accent)' : 'var(--ink-3)') + '" stroke-width="1.2"/>';
  let h = '<svg class="bases" width="32" height="22" viewBox="0 0 32 22" aria-label="' + esc(baseOutText(b, outs)) + '">' + sq(25, 14, on[0]) + sq(16, 6, on[1]) + sq(7, 14, on[2]) + '</svg>';
  if (isNum(outs)) h += '<span class="outs-dots">' + [0, 1, 2].map(i => '<i class="' + (i < outs ? 'on' : '') + '"></i>').join('') + '</span>';
  return '<span class="bases-wrap">' + h + '</span>';
}
function baseOutText(b, outs) {
  const on = basesOf(b);
  const names = ['1st', '2nd', '3rd'].filter((_, i) => on[i]);
  const bt = !names.length ? 'bases empty' : names.length === 3 ? 'bases loaded' : 'runner' + (names.length > 1 ? 's' : '') + ' on ' + names.join(' and ');
  return bt + (isNum(outs) ? ', ' + outsText(outs) : '');
}
function pitchName(t) { return PITCH_NAMES[String(t || '').toUpperCase()] || String(t || '—'); }
function pitchColour(t) { return PITCH_COLOURS[String(t || '').toUpperCase()] || C.text3; }
function pitchChip(t) {
  const c = pitchColour(t);
  return '<span class="pt-chip" style="border-color:' + c + ';color:' + c + '" title="' + esc(pitchName(t)) + '">' + esc(String(t || '?').toUpperCase()) + '</span>';
}
/* A pitch's call/description: {label, colour, kind}. */
function callInfo(desc) {
  const k = String(desc || '');
  const r = CALLS[k] || CALLS[k.toLowerCase()];
  if (r) return { label: r[0], colour: r[1], kind: r[2] };
  return { label: titleCase(k) || '—', colour: C.text3, kind: 'other' };
}
function eventLabel(ev) {
  const map = { single: 'Single', double: 'Double', triple: 'Triple', home_run: 'Home run', walk: 'Walk', intent_walk: 'Intentional walk',
    strikeout: 'Strikeout', strikeout_double_play: 'Strikeout double play', hit_by_pitch: 'Hit by pitch', field_out: 'Out', force_out: 'Force out',
    grounded_into_double_play: 'Double play', double_play: 'Double play', triple_play: 'Triple play', fielders_choice: "Fielder's choice",
    fielders_choice_out: "Fielder's choice", sac_fly: 'Sacrifice fly', sac_bunt: 'Sacrifice bunt', field_error: 'Error', catcher_interf: 'Interference',
    sac_fly_double_play: 'Sac fly double play', truncated_pa: 'Truncated PA' };
  return map[ev] || titleCase(ev || '');
}
function isHit(ev) { return ['single', 'double', 'triple', 'home_run'].indexOf(ev) >= 0; }
/* Postseason round from a game type (F/D/L/W) or a round key (WC/DS/LCS/WS). */
function roundLabel(r, short) { return (short ? ROUND_SHORT : ROUND_LONG)[r] || String(r || ''); }
function roundKey(r) { return ROUND_KEY[r] || String(r || ''); }

/* Status of a GAME_CARD / game: 'pre' | 'live' | 'final' | 'postponed' | 'cancelled' | 'suspended' | 'delayed'. */
function gameState(g) {
  const s = String((g && g.status) || '').toLowerCase();
  if (s === 'live' || s === 'in' || s === 'in progress' || s === 'inprogress') return 'live';
  if (s === 'final' || s === 'post' || s === 'done' || s === 'completed' || s === 'game over') return 'final';
  if (s === 'pre' || s === 'scheduled' || s === 'upcoming' || s === 'preview' || s === 'warmup' || !s) return 'pre';
  return s;
}
function isFinal(g) { return gameState(g) === 'final'; }
function isLive(g) { return gameState(g) === 'live'; }
/* A status chip: start time, live inning, Final (F/10 when extra), Postponed. */
function statusChip(g) {
  const st = gameState(g);
  if (st === 'live') {
    const inn = isNum(g.inning) ? ' · ' + inningLabel(g.inning, g.half, true) : '';
    return '<span class="chip st-live"><span class="live-dot"></span> Live' + esc(inn) + '</span>';
  }
  if (st === 'final') {
    const n = g.innings && g.innings.length ? g.innings.length : (isNum(g.inning) ? g.inning : 9);
    return '<span class="chip st-ft">Final' + (n > 9 ? '/' + n : (n < 9 && n >= 5 ? '/' + n : '')) + '</span>';
  }
  if (st === 'pre') {
    const t = fmtTime(g.start || g.date);
    return '<span class="chip st-time">' + esc(t || 'TBD') + '</span>';
  }
  return '<span class="chip warn">' + esc(titleCase(st)) + '</span>';
}
/* "NL Wild Card Series · Game 3 of 3" (or the series summary when the payload carries one). */
function seriesText(s, short) {
  if (!s) return '';
  if (typeof s === 'string') return s;
  if (s.summary) return String(s.summary);
  const desc = s.desc || roundLabel(s.round) || '';
  return (short ? desc.replace('Wild Card Series', 'WC').replace('Division Series', 'DS').replace('Championship Series', 'CS') : desc) +
    (isNum(s.game) ? ' · Game ' + s.game + (isNum(s.of) && !short ? ' of ' + s.of : '') : '');
}

// ── names, teams, links ────────────────────────────────────────────────────

function lvl(L) { return isLevel(L) ? L : state.level; }
function player(pid) { return NAMES[String(pid)] || {}; }
function playerInfo(pid) { return player(pid); }
function playerName(pid) { const x = NAMES[String(pid)]; return x && x.name ? x.name : (pid ? 'Player ' + pid : '—'); }
function playerShort(pid) {
  const x = NAMES[String(pid)] || {};
  if (x.short) return x.short;
  const n = playerName(pid).split(' ');
  return n.length > 1 ? n[0].charAt(0) + '. ' + n.slice(1).join(' ') : n[0];
}
function playerSurname(pid) {
  const n = playerName(pid).split(' ');
  if (n.length < 2) return n[0];
  const sfx = /^(Jr\.?|Sr\.?|II|III|IV)$/i.test(n[n.length - 1]);
  return sfx && n.length > 2 ? n[n.length - 2] + ' ' + n[n.length - 1] : n.slice(1).join(' ');
}
/* A pitcher by position (P, SP, RP); two-way players (TWP) count as both. */
function isPitcher(pid) { const p = String((NAMES[String(pid)] || {}).pos || '').toUpperCase(); return p === 'P' || p === 'SP' || p === 'RP' || p === 'TWP'; }
/* '?s=S' when S is not the level's current season, else ''. */
function sq(L, S) {
  const l = lvl(L);
  const s = S || (l === state.level ? state.season : null);
  return s && Number(s) !== currentSeason(l) ? '?s=' + s : '';
}
/* '#/<L>/<sub>' plus the season query: href('standings') -> '#/mlb/standings'. */
function href(sub, L, S) {
  const l = lvl(L);
  const s = String(sub || '').replace(/^\/+/, '');
  return '#/' + l + (s ? '/' + s : '') + sq(l, S);
}
/* A global route ('#/postseason'), with the season query when it is not current. */
function ghref(sub, S) { return '#/' + String(sub || '').replace(/^\/+/, '') + sq(state.level, S); }
/* opts {role: 'hitter'|'pitcher' (default from the position), level, season}. */
function playerHref(pid, opts) {
  const o = typeof opts === 'string' ? { role: opts } : (opts || {});
  const role = o.role || (isPitcher(pid) && String(player(pid).pos).toUpperCase() !== 'TWP' ? 'pitcher' : 'hitter');
  return href(role + '/' + encodeURIComponent(pid), o.level, o.season);
}
/* <a> to the player page. opts {name, short: true, surname: true, role, team: true (abbr after), pos: true, level, season} or a name string. */
function playerLink(pid, opts) {
  if (!pid) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.surname ? playerSurname(pid) : o.short ? playerShort(pid) : playerName(pid));
  const x = player(pid);
  const tail = (o.pos && x.pos ? '<span class="pl-pos">' + esc(x.pos) + '</span>' : '') + (o.team && x.team ? '<span class="pl-team">' + esc(teamAbbr(x.team)) + '</span>' : '');
  return '<a class="ply-link" href="' + playerHref(pid, o) + '">' + esc(label) + tail + '</a>';
}
function teamInfo(tid) { return TEAMS[String(tid)] || {}; }
function teamName(tid) { const x = TEAMS[String(tid)]; return x && x.name ? x.name : (tid ? 'Team ' + tid : '—'); }
function teamShort(tid) { const x = TEAMS[String(tid)] || {}; return x.short || x.name || (tid ? String(tid) : '—'); }
function teamAbbr(tid) {
  const x = TEAMS[String(tid)] || {};
  if (x.abbr) return x.abbr;
  if (x.name) return x.name.split(' ').map(w => w.charAt(0)).join('').slice(0, 3).toUpperCase();
  return tid ? String(tid) : '—';
}
function hexRGB(hex) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return null;
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function lum(rgb) { return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255; }
/* A team's colour, lifted toward white until it reads on the dark theme (most club navies do not). */
function teamColour(tid) {
  const x = TEAMS[String(tid)] || {};
  const rgb = hexRGB(x.colour);
  if (!rgb) return x.placeholder ? C.text3 : PALETTE[hashIndex(tid || '?', PALETTE.length)];
  if (window.QK) return QK.color.team(x.colour);
  let c = rgb.slice(), k = 0;
  while (lum(c) < 0.32 && k < 12) { c = c.map(v => Math.round(v + (255 - v) * 0.14)); k++; }
  return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
}
/* The kit's team mark (a contrast-checked monogram in the club colour; no logos). */
function teamMark(tid, size) {
  const x = TEAMS[String(tid)] || {};
  return window.QK ? QK.teamMark({ name: x.name || String(tid), abbr: x.abbr || teamAbbr(tid), colour: x.colour }, size) : teamBar(tid);
}
function teamObj(tid, L, S) { const x = TEAMS[String(tid)] || {}; return { name: x.short || x.name || String(tid), abbr: x.abbr || teamAbbr(tid), colour: x.colour, href: teamHref(tid, L, S) }; }
/* The raw club colour (for fills behind white text). */
function teamColourRaw(tid) { const x = TEAMS[String(tid)] || {}; return x.colour || C.bg3; }
function teamBar(tid) { return '<span class="team-bar" style="background:' + teamColour(tid) + '"></span>'; }
function teamHref(tid, L, S) { return href('team/' + encodeURIComponent(tid), L, S); }
/* <a> to the team page. opts {abbr: true, short: true, bar: true (default), name, level, season}. Placeholder teams are plain text. */
function teamLink(tid, opts) {
  if (!tid) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.abbr ? teamAbbr(tid) : o.short ? teamShort(tid) : teamName(tid));
  const bar = o.bar === false ? '' : teamBar(tid);
  if (teamInfo(tid).placeholder) return '<span class="team-link tbd">' + bar + esc(label) + '</span>';
  return '<a class="team-link" href="' + teamHref(tid, o.level, o.season) + '" title="' + esc(teamName(tid)) + '">' + bar + esc(label) + '</a>';
}
function hashIndex(s, n) { let h = 0; String(s).split('').forEach(ch => { h = (h * 31 + ch.charCodeAt(0)) >>> 0; }); return h % n; }
function playerColour(pid) { return pid ? PALETTE[hashIndex(pid, PALETTE.length)] : C.text3; }
function gameHref(gpk, L, S) { return href('game/' + encodeURIComponent(gpk), L, S); }
/* <a> to the game centre (label default "Game centre"). */
function gameLink(gpk, label, L, S) {
  if (!gpk) return '<span class="muted-inline">—</span>';
  return '<a class="game-link" href="' + gameHref(gpk, L, S) + '">' + esc(label || 'Game centre') + '</a>';
}
function umpireName(id) { const x = UMPS[String(id)]; return x && x.name ? x.name : (id ? 'Umpire ' + id : '—'); }
function umpireHref(id) { return ghref('umpire/' + encodeURIComponent(id)); }
function umpireLink(id, name) {
  if (!id) return '<span class="muted-inline">—</span>';
  return '<a class="ump-link" href="' + umpireHref(id) + '">' + esc(name || umpireName(id)) + '</a>';
}
function parkInfo(vid) { return VENUES[String(vid)] || {}; }
function parkName(vid) { const x = VENUES[String(vid)]; return x && x.name ? x.name : (vid ? 'Venue ' + vid : '—'); }
function parkHref(vid) { return ghref('park/' + encodeURIComponent(vid)); }
function parkLink(vid, name) {
  if (!vid) return '<span class="muted-inline">—</span>';
  return '<a class="park-link" href="' + parkHref(vid) + '">' + esc(name || parkName(vid)) + '</a>';
}
function compareHref(a, b) { return '#/compare' + (a ? '/' + encodeURIComponent(a) : '') + (b ? '/' + encodeURIComponent(b) : ''); }
function glossHref(key) { return '#/glossary' + (key ? '/' + encodeURIComponent(key) : ''); }

/* A GAME_CARD as the kit's v2 game card (QK.gameCard; index.json today/recent/upcoming, schedule.json), linking to the
 * game centre: the two clubs with our (or, live, the in-game) win chance, the favourite in the signal colour, the
 * win-probability bar, records (BP.records, filled by pages that load season.json), recent form (BP.forms), the
 * probable starters and our expected total runs. Kit v3: no market on cards unless opts.market === true (game detail
 * only); opts.why adds the italic one-line reason (QK.whyLine).
 * opts {level, season, date: true (show the date), compact, series: true (default), market: false, why}. */
const RECORDS = {}, FORMS = {};
/* A postseason game that was never needed (series decided; Stats API status cancelled / not_needed): hidden everywhere. */
function notNeeded(g) { return !!g && (g.not_needed === true || (String(g.status || '').toLowerCase() === 'cancelled' && g.gtype && g.gtype !== 'R')); }
function setRecords(map) { Object.keys(RECORDS).forEach(k => { delete RECORDS[k]; }); Object.keys(map || {}).forEach(k => { RECORDS[k] = map[k]; }); }
function setForms(map) { Object.keys(FORMS).forEach(k => { delete FORMS[k]; }); Object.keys(map || {}).forEach(k => { FORMS[k] = map[k]; }); }
function gameCard(g, opts) {
  const o = opts || {};
  const L = o.level || state.level;
  if (!g) return '';
  const st = gameState(g);
  const live = st === 'live', fin = st === 'final', pre = !live && !fin;
  const m = g.model || {}, mk = g.market || null;
  const k = kitGame(g, L);
  if (o.season) k.href = gameHref(g.gpk || g.id, L, o.season);
  const tag = o.series === false ? '' : (g.series ? seriesText(g.series, true) : (g.gtype && g.gtype !== 'R' ? roundLabel(g.gtype) : ''));
  k.league = [o.date ? fmtDate(g.date, { year: false }) : '', tag || (L === 'aaa' ? 'Triple-A' : 'MLB')].filter(Boolean).join(' · ');
  const prob = g.probables || {};
  const sub = side => {
    const bits = [];
    if (RECORDS[String(g[side])]) bits.push(RECORDS[String(g[side])]);
    return bits.join(' · ');
  };
  k.away.record = sub('away'); k.home.record = sub('home');
  if (FORMS[String(g.away)]) k.away.form = FORMS[String(g.away)];
  if (FORMS[String(g.home)]) k.home.form = FORMS[String(g.home)];
  if (o.market !== true || !mk) k.market_home = null;
  let html = window.QK && QK.gameCard ? QK.gameCard(k, { sport: false, why: !!o.why, market: o.market === true, marketLabel: 'Market', marketTip: 'The prediction-market or no-vig line probability for the home side, a reference, not our forecast' }) : '';
  const extra = [];
  if (isNum(m.total) && !fin) extra.push('<span data-tip="Our expected total runs from the plate-appearance simulation">' + num(m.total, 1) + ' runs expected</span>');
  if (live && isNum(g.outs)) extra.push('<span>' + esc(outsText(g.outs)) + '</span>');
  if (pre && (prob.home || prob.away)) extra.push('<span class="bp-gc-sp" title="Probable starters">SP ' + esc(prob.away ? playerSurname(prob.away) : 'TBD') + ' v ' + esc(prob.home ? playerSurname(prob.home) : 'TBD') + '</span>');
  if (extra.length) {
    const i = html.lastIndexOf('</a>');
    if (i > 0) html = html.slice(0, i) + '<div class="bp-gc-extra">' + extra.join('') + '</div>' + html.slice(i);
  }
  if (o.compact) html = html.replace('class="qk-gc', 'class="qk-gc gc-compact');
  return html;
}
/* A GAME_CARD in the kit's shared game shape (QK.matchCard, QK.tick). */
function kitGame(g, L) {
  const st = gameState(g), m = g.model || {}, mk = g.market || {};
  const live = st === 'live';
  return { sport: 'baseball', league: g.series ? seriesText(g.series, true) : (L === 'aaa' ? 'Triple-A' : 'MLB'), id: g.gpk, start: g.start || g.date,
    status: st === 'live' ? 'live' : st === 'final' ? 'final' : 'pre', home: teamObj(g.home, L), away: teamObj(g.away, L),
    hs: isNum(g.hs) ? g.hs : null, as: isNum(g.as) ? g.as : null,
    p_home: live && isNum(g.wp_home) ? g.wp_home : (isNum(m.p_home) ? m.p_home : null), market_home: isNum(mk.p_home) ? mk.p_home : null,
    /* v3: live, the kit reads the live chance and keeps our pre-game call for "before the start we had ..." */
    p_pre: live && isNum(g.wp_home) && isNum(m.p_home) ? m.p_home : null, pre_only: live && !isNum(g.wp_home) ? true : undefined,
    period: isNum(g.inning) ? g.inning : null, href: gameHref(g.gpk, L) };
}
/* A market TITLE dict -> {id: p} (de-vigged "probs", else "prices", else the raw "mid"); {} when unavailable. */
function titleProbs(t) {
  if (!t || t.available === false) return {};
  return t.probs || t.prices || t.mid || {};
}

// ── levels and seasons ─────────────────────────────────────────────────────

function levelInfo(L) {
  const l = lvl(L);
  const d = INDEX.data;
  return (d && d.levels && d.levels[l]) || {};
}
function currentSeason(L) {
  const i = levelInfo(L);
  if (isNum(i.season)) return Number(i.season);
  const d = INDEX.data;
  return d && isNum(d.season) ? Number(d.season) : new Date().getFullYear();
}
function seasons(L) {
  const l = lvl(L);
  const i = levelInfo(l);
  const list = (i.seasons && i.seasons.length ? i.seasons.map(Number) : [currentSeason(l)]).slice();
  if (list.indexOf(currentSeason(l)) < 0) list.push(currentSeason(l));
  return list.sort((a, b) => b - a);
}
function levelName(L) { return LEVEL_NAME[lvl(L)]; }
function levelLong(L) { return LEVEL_LONG[lvl(L)]; }
function phase(L) {
  const i = levelInfo(L);
  const d = INDEX.data || {};
  return String(i.phase || d.phase || '');
}

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
      /* a string with tags is HTML (as the kit's QK.tableHTML treats it); other primitives are text */
      const c = (c0 !== null && typeof c0 === 'object') ? c0 : (typeof c0 === 'string' && /<[a-z]/i.test(c0) ? { html: c0 } : { v: c0 });
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
        ths.forEach(x => { if (x.classList.contains('sortable-th')) x.setAttribute('aria-sort', x === th ? (asc ? 'ascending' : 'descending') : 'none'); });
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
/* Percentiles on the kit's v2 scale, the same on every site: cold blue (worst in the peer group) through grey to hot
 * red (best); p is 0-100 and already oriented (lower-is-better metrics flipped in the payloads). */
function tokenOf(n, dflt) { const v = window.QK ? QK.cssVar(n) : ''; return v || dflt; }
function pctColor(p) {
  if (!isNum(p)) return 'var(--s-3)';
  return window.QK && QK.pctHex ? QK.pctHex(p) : 'var(--pc-50)';
}
/* Ink for text on a percentile colour. */
function pctInk(p) { if (!isNum(p) || !window.QK) return 'var(--ink-1)'; return QK.pctInk ? QK.pctInk(p) : '#fff'; }
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
/* A v2 stat tile (QK.statTile); value and sub are HTML. */
function statTile(label, value, sub, cls) {
  if (window.QK && QK.statTile) return QK.statTile({ label: label, value: value === undefined || value === null ? '—' : value, sub: sub || '', html: true, cls: cls || '' });
  return '<div class="qk-kpi kpi' + (cls ? ' ' + cls : '') + '"><div class="qk-kpi-label kpi-label">' + esc(label) + '</div>' +
    '<div class="qk-kpi-value kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="qk-kpi-sub kpi-sub">' + sub + '</div>' : '') + '</div>';
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
/* Sequential colour for t in [0,1] (the clay accent). */
function seqColour(t) {
  if (!isNum(t)) return 'transparent';
  const u = Math.max(0, Math.min(1, t));
  return 'rgba(217,128,78,' + (0.05 + 0.75 * u).toFixed(3) + ')';
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
/* A page head inside a section: the kit's v2 section head (title, sub-line and the links at the right). */
function pageHead(title, sub, right) {
  if (window.QK && QK.sectionHead) return QK.sectionHead({ title: esc(title), sub: sub || '', actions: right ? '<div class="bp-ph-links">' + right + '</div>' : '', html: true });
  return '<div class="page-head"><div><h2>' + esc(title) + '</h2>' + (sub ? '<div class="ph-sub">' + sub + '</div>' : '') + '</div>' +
    (right ? '<div class="ph-nav">' + right + '</div>' : '') + '</div>';
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

// ── header: level switch, season picker, nav, meta, search ─────────────────

function setLevelState(L) {
  if (!isLevel(L)) return;
  state.level = L;
  try { window.localStorage.setItem(LS_LEVEL, L); } catch (e) { /* private mode */ }
}
/* Switch level, keeping the page type where it makes sense. */
function switchLevel(L) {
  if (!isLevel(L)) return;
  const r = state.route || 'hub';
  let to = SWITCH_TO[r] || r;
  if (to === 'notfound' || !routeEntry(to)) to = 'hub';
  if ((routeEntry(to) || {}).global) {
    setLevelState(L);
    const h = String(location.hash || '#/').replace(/^#\/(mlb|aaa|npb)\//, '#/').replace(/\?.*$/, '');
    if (h !== location.hash) go(h); else render();
    return;
  }
  if (to === 'hub') go('#/' + L);
  else go('#/' + L + '/' + routeEntry(to).pattern.replace(/\/:.*$/, ''));
}
/* Change the season shown, keeping the page where it makes sense. */
function setSeason(S) {
  const y = parseInt(S, 10);
  if (isNaN(y)) return;
  const L = state.level, r = state.route || 'hub';
  if (r === 'game') { go(href('games', L, y)); return; }
  const h = String(location.hash || '#/' + L).replace(/\?.*$/, '');
  const q = Object.assign({}, state.params.query || {});
  delete q.y; delete q.season;
  if (y === currentSeason(L)) delete q.s; else q.s = String(y);
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  let base = h === '#/' || h === '#' ? '#/' + L : h;
  if (r === 'games' && state.params.date) base = base.replace(/\/games\/[^/]+$/, '/games');
  go(base + (qs ? '?' + qs : ''));
}
let pickerFilled = false;
let SHELL = null;
/* The level switch and season picker sit at the right of the section nav (the shell's ctx slot). */
function ctxHTML() {
  return '<div class="qk-seg bp-level" role="group" aria-label="Level">' + LEVELS.map(l =>
    '<button type="button" data-level="' + l + '" aria-pressed="' + (l === state.level) + '" title="' + esc(LEVEL_LONG[l]) + '">' + esc(LEVEL_NAME[l]) + '</button>').join('') + '</div>' +
    '<select class="qk-select bp-season" id="season-select" aria-label="Season"></select>';
}
function fillSeasonPicker() {
  const sel = document.getElementById('season-select');
  if (!sel) return;
  const L = state.level;
  const list = seasons(L);
  if (state.season && list.indexOf(state.season) < 0) list.unshift(state.season);
  sel.innerHTML = list.map(y => '<option value="' + y + '">' + y + '</option>').join('');
  sel.value = String(state.season || currentSeason(L));
  pickerFilled = true;
}
/* Section hrefs follow the level and season shown. */
function sectionHrefs(L, S) {
  return { overview: '#/' + L + sq(L, S), fixtures: href('games', L, S), standings: href('standings', L, S), teams: href('teams', L, S),
    players: href('hitters', L, S), value: href('value', L, S), fantasy: '#/mlb/fantasy', lab: href('lab', L, S), model: '#/methodology' };
}
function updateHeader() {
  const L = state.level, S = state.season;
  if (document.body) { LEVELS.forEach(l => document.body.classList.toggle('lv-' + l, l === L)); }
  document.querySelectorAll('.bp-level button[data-level]').forEach(b => b.setAttribute('aria-pressed', b.dataset.level === L ? 'true' : 'false'));
  const links = sectionHrefs(L, S);
  document.querySelectorAll('.qk-secnav a[data-sec]').forEach(a => { if (links[a.dataset.sec]) a.setAttribute('href', links[a.dataset.sec]); });
  const brand = document.querySelector('.qk-brand');
  if (brand && !brand.dataset.home) { brand.dataset.home = '1'; }
}
function markNav(key) { if (SHELL) SHELL.setSection(key); }
function setMeta(html) {
  const el = document.getElementById('meta-line');
  if (!el) return;
  const d = INDEX.data;
  const base = d && d.updated_at ? 'Updated ' + esc(fmtStamp(d.updated_at)) : '';
  el.innerHTML = [html, base].filter(Boolean).join(' · ');
}

function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
let SEARCH = null;
/* The search palette's rows: every club (MLB and Triple-A) and every player in players_index.json. */
function loadSearch() {
  if (SEARCH) return SEARCH;
  SEARCH = ensureNames().then(() => {
    const items = [];
    Object.keys(TEAMS).forEach(tid => {
      const x = TEAMS[tid];
      if (!x.name || x.placeholder || x.level === 'npb') return;
      const L = x.level === 'aaa' ? 'aaa' : 'mlb';
      items.push({ sport: 'baseball', t: x.name, s: [L === 'aaa' ? 'Triple-A club' + (x.parent ? ' · ' + teamAbbr(x.parent) : '') : 'Club · ' + (x.division || 'MLB'), x.abbr].filter(Boolean).join(' · '),
        href: teamHref(tid, L), order: L === 'mlb' ? 0 : 2 });
    });
    Object.keys(NAMES).forEach(pid => {
      const x = NAMES[pid] || {};
      if (!x.name) return;
      const lv = Array.isArray(x.levels) ? x.levels : (x.levels ? String(x.levels).split(/[,|]/) : []);
      if (lv.length && lv.every(v => String(v).toLowerCase() === 'npb')) return;
      const L = lv.indexOf('mlb') >= 0 || !lv.length ? 'mlb' : 'aaa';
      items.push({ sport: 'baseball', t: x.name, s: [x.pos ? (isPitcher(pid) ? 'Pitcher' : 'Hitter') + ' · ' + x.pos : 'Player', x.team ? teamAbbr(x.team) : '', lv.length ? lv.filter(v => String(v).toLowerCase() !== 'npb').map(v => String(v).toUpperCase()).join('/') : ''].filter(Boolean).join(' · '),
        href: playerHref(pid, { level: L }), order: L === 'mlb' ? 1 : 3 });
    });
    items.sort((a, b) => a.order - b.order);
    return items;
  });
  return SEARCH;
}
function closeSearch() { /* the palette closes itself on navigation */ }
function initHeader() {
  const sel = document.getElementById('season-select');
  if (sel) sel.addEventListener('change', () => setSeason(sel.value));
  document.querySelectorAll('.bp-level button[data-level]').forEach(b => b.addEventListener('click', () => switchLevel(b.dataset.level)));
}
function liveAny() {
  const d = INDEX.data || {};
  const cards = [].concat(d.today || [], ((d.levels || {}).aaa || {}).today || []);
  return cards.some(isLive);
}
function init() {
  if (window.QK) {
    SHELL = QK.shell({
      sport: 'baseball', section: 'overview',
      sections: QK.sections('baseball').map(s => Object.assign({}, s, { href: s.key === 'overview' ? '#/' : '#/' + s.key })),
      ctx: ctxHTML(),
      search: { load: loadSearch }
    });
  }
  load('index.json').then(idx => {
    INDEX.data = idx;
    initHeader();
    if (SHELL) SHELL.setLive({ baseball: liveAny() });
    booted = true;
    window.addEventListener('hashchange', render);
    render();
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else setTimeout(init, 0);

return {
  // state and routing
  state: state, route: route, routeNpb: routeNpb, go: go, parseHash: parseHash, onLeave: onLeave, interval: interval, render: render,
  ROUTES: ROUTES, HANDLERS: HANDLERS, TITLES: TITLES, LEVELS: LEVELS, LEVEL_NAME: LEVEL_NAME, LEVEL_LONG: LEVEL_LONG, SITE: SITE,
  switchLevel: switchLevel, setSeason: setSeason, setMeta: setMeta,
  // data
  load: load, loadAll: loadAll, uncache: uncache, refreshIndex: refreshIndex, liveRefresh: liveRefresh, ok: ok, reason: reason, cached: cached, lpath: lpath, ypath: ypath, gamePath: gamePath, playerPath: playerPath,
  loadLevel: loadLevel, loadYear: loadYear, marketsPath: marketsPath, loadGame: loadGame, ensureNames: ensureNames, playersOf: playersOf,
  index: () => INDEX.data, levelInfo: levelInfo, currentSeason: currentSeason, seasons: seasons, levelName: levelName, levelLong: levelLong,
  isLevel: isLevel, phase: phase,
  NAMES: NAMES, TEAMS: TEAMS, UMPS: UMPS, VENUES: VENUES, DIVISIONS: DIVISIONS,
  // formatting
  esc: esc, num: num, int: int, pct: pct, signed: signed, pp: pp, fmtAvg: fmtAvg, fmtIP: fmtIP, fmtDate: fmtDate, fmtTime: fmtTime,
  fmtStamp: fmtStamp, localDay: localDay, todayISO: todayISO, addDays: addDays, countdown: countdown, ordinal: ordinal, fmtVal: fmtVal,
  metric: metric, record: record, american: american, decimal: decimal, fmtOdds: fmtOdds, amToProb: amToProb, devigAm: devigAm, devig2: devig2,
  fmtLine: fmtLine, parseDate: parseDate, isNum: isNum, titleCase: titleCase,
  // baseball
  PITCH_NAMES: PITCH_NAMES, PITCH_COLOURS: PITCH_COLOURS, PITCH_ORDER: PITCH_ORDER, CALLS: CALLS,
  halfOf: halfOf, inningLabel: inningLabel, countText: countText, outsText: outsText, basesOf: basesOf, basesHTML: basesHTML, baseOutText: baseOutText,
  pitchName: pitchName, pitchColour: pitchColour, pitchChip: pitchChip, callInfo: callInfo, eventLabel: eventLabel, isHit: isHit,
  roundLabel: roundLabel, roundKey: roundKey, gameState: gameState, isFinal: isFinal, isLive: isLive, statusChip: statusChip, seriesText: seriesText,
  gameCard: gameCard, titleProbs: titleProbs, notNeeded: notNeeded, setRecords: setRecords, setForms: setForms, RECORDS: RECORDS, FORMS: FORMS,
  // names and links
  player: player, playerInfo: playerInfo, playerName: playerName, playerShort: playerShort, playerSurname: playerSurname, isPitcher: isPitcher,
  playerColour: playerColour, playerLink: playerLink, playerHref: playerHref,
  teamInfo: teamInfo, teamName: teamName, teamShort: teamShort, teamAbbr: teamAbbr, teamColour: teamColour, teamColourRaw: teamColourRaw,
  teamBar: teamBar, teamHref: teamHref, teamLink: teamLink,
  gameHref: gameHref, gameLink: gameLink, umpireName: umpireName, umpireHref: umpireHref, umpireLink: umpireLink,
  parkInfo: parkInfo, parkName: parkName, parkHref: parkHref, parkLink: parkLink, compareHref: compareHref, glossHref: glossHref,
  href: href, ghref: ghref, sq: sq,
  // HTML
  card: card, muted: muted, chip: chip, notBuilt: notBuilt, tableHTML: tableHTML, sortable: sortable, pctPill: pctPill, pctColor: pctColor,
  pctRow: pctRow, statTile: statTile, probCell: probCell, edgeHTML: edgeHTML, splitBar: splitBar, divColour: divColour, seqColour: seqColour,
  toggles: toggles, wireToggles: wireToggles, pageHead: pageHead, pctInk: pctInk, alpha: alpha, teamMark: teamMark, teamObj: teamObj, kitGame: kitGame,
  SECTION_OF: SECTION_OF, SECTION_TABS: SECTION_TABS, shell: () => SHELL, liveAny: liveAny,
  // charts
  plot: plot, layout: layout, PALETTE: PALETTE, C: C, DARK_LAYOUT: DARK_LAYOUT, PLOTLY_CONF: PLOTLY_CONF,
  FOOTBALL_URL: FOOTBALL_URL, PADDOCK_URL: PADDOCK_URL, HARDWOOD_URL: HARDWOOD_URL, ACE_URL: ACE_URL, GRIDIRON_URL: GRIDIRON_URL, RINK_URL: RINK_URL,
  charts: {}
};
})();
