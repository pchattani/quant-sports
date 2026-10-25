/* The Quant Footballer — Value & Transfers (#/value[/<tab>]).
 *
 *   #/value                players: goals above replacement, last 12 months (or ?v=season: this season by
 *                          competition); filters ?v=season&c=<slug>&t=<tier>&club=<tid>&r=<role>&min=<n>&q=<text>
 *   #/value/positions      the best at each position under the same filters
 *   #/value/transfers      the transfers feed with grades (?lg=&k=&w=&q=); ?view=deals best and worst deals;
 *                          ?view=windows window summaries by league (?lg=)
 *   #/value/simulator      the transfer simulator: ?p=<player id>&to=<buying club id>&out=<id,id>
 *   #/value/budgets        the budget model, league windows and one club's budget and ledger (?lg=&club=)
 *   #/value/method         how the number is made: weights, held-out checks, replacement levels, fee model
 *   FB.valueNeeds(el, tid) the club page's strengths-and-needs card (targets, budget, ledger), exported for clubs.js
 *   FB.moves               who moves next (value/moves.json and the clubs' `movement`, UNIFIED_PAYLOADS 15;
 *                          docs/_design/MOVES_VIEWS.md): the squad's "chance of moving" cell and key, the club's
 *                          outlook and targets (clubs.js); FB.movementCard(el, pid, {tid, until}) the player's card
 *                          (players.js). Every view draws nothing when the payload has no movement.
 *
 * Reads data/value/meta.json, players.json, lines.json, transfers.json, club/<tid>.json (UNIFIED_PAYLOADS
 * 11-12), and each followed league's teams.json, probs.json and sensitivity.json. value/club/<tid>.json exists
 * exactly for the clubs in the thirteen followed leagues' teams.json, so only those are ever requested.
 * The simulator interpolates the build's sensitivity curves and evaluates the fee model's published
 * coefficients for the chosen buyer; every other number comes from a payload. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, pct = FB.pct, signed = FB.signed, money = FB.money;

var ROLE_ORDER = ['GK', 'CB', 'FB', 'DM', 'CM', 'AM', 'W', 'ST', 'DF', 'MF', 'FW'];
var MAIN_ROLES = ['GK', 'CB', 'FB', 'DM', 'CM', 'AM', 'W', 'ST'];
var UNIT_OF = { GK: 'GK', CB: 'CB', FB: 'FB', DM: 'MID', CM: 'MID', AM: 'ATT', W: 'ATT', ST: 'ST', DF: 'CB', MF: 'MID', FW: 'ST' };
var ROLE_SLOT = { GK: 4, CB: 1, FB: 7, DM: 3, CM: 6, AM: 5, W: 2, ST: 8, DF: 1, MF: 6, FW: 8 };
var MINUTES_CAP = 85;
var HONEST = 'Model suggestions based on on-field value and our fair-fee and budget models; not considering wages, contracts, fit or availability unless shown.';
var KIND_LABEL = { fee: 'Transfer', free: 'Free', undisclosed: 'Undisclosed fee', loan: 'Loan', loan_end: 'Loan return', youth: 'Promoted' };
var TABS = [['', 'Players'], ['positions', 'Best by position'], ['transfers', 'Transfers'], ['simulator', 'Simulator'], ['budgets', 'Budgets'], ['method', 'Method']];

function has(v) { return isNum(v); }
function g2(v) { return has(v) ? signed(v, 2) : '—'; }
function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function roleColor(r) { return 'var(--c-' + (ROLE_SLOT[r] || 8) + ')'; }
function roleHex(r) { return QK.cssVar('--c-' + (ROLE_SLOT[r] || 8)); }
function roleLabel(r) { return ((META || {}).roles || {})[r] || r || ''; }
function roleLegend() { return '<div class="qk-legend fb-mt">' + MAIN_ROLES.map(function (r) { return '<span><i class="dot" style="--k:' + roleColor(r) + '"></i>' + esc(r) + '</span>'; }).join('') + '</div>'; }
function roleBadge(r) { return r ? '<span class="fb-va-role" style="--k:' + roleColor(r) + '" title="' + esc(roleLabel(r)) + '">' + esc(r) + '</span>' : ''; }
function compName(slug) { var c = FB.comp(slug); if (c) return c.short_name || c.name; var m = ((META || {}).comps || {})[slug]; return m ? (m.short || m.name) : (slug || '—'); }
function moneyRange(lo, hi) { return has(lo) && has(hi) ? money(lo) + '–' + money(hi) : '—'; }
function grade(g, tip) { return g ? '<span class="fb-va-grade g-' + esc(g) + '"' + (tip ? ' data-tip="' + esc(tip) + '"' : '') + '>' + esc(g) + '</span>' : '<span class="qk-muted">—</span>'; }
function kindTag(k) { return '<span class="fb-va-kind k-' + esc(k) + '">' + esc(KIND_LABEL[k] || k) + '</span>'; }
function plink(id, name) { return FB.playerLink(id, name || ('#' + id)); }
/* Crest files exist only for clubs whose competition teams.json names one (most clubs have none): link without a crest otherwise. */
var CRESTS = {};
function crestOk(tid) { return !!CRESTS[String(tid)]; }
function clink(tid, name) { return name ? FB.clubLink(tid, name, { nocrest: !crestOk(tid) }) : '<span class="qk-muted">—</span>'; }
function crest(tid, name) { return crestOk(tid) ? FB.crest(tid, name, 'sm') : ''; }
function netText(v) { return has(v) ? (v < 0 ? '−' : '') + money(Math.abs(v)) : '—'; }
function intl(v) { return has(v) ? Math.round(v).toLocaleString('en-GB') : '—'; }

var META = null, PLAYERS = null, BYID = null, LINES = null, LEAGUE_CLUBS = null;
function feeOn() { return !!(((META || {}).fee || {}).fitted); }

/* the components that drive a value, largest first */
function drivers(c, n) {
  var names = (META || {}).components || [];
  if (!c || !names.length) return '';
  return c.map(function (v, i) { return [names[i], v]; }).filter(function (x) { return has(x[1]) && Math.abs(x[1]) >= 0.01; })
    .sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); }).slice(0, n || 2)
    .map(function (x) { return '<span class="fb-va-drv ' + (x[1] > 0 ? 'up' : 'down') + '">' + esc(x[0]) + ' ' + signed(x[1], 2) + '</span>'; }).join(' ');
}

function loadCore() {
  if (META && PLAYERS) return Promise.resolve(true);
  return FB.loadAll(['value/meta.json', 'value/players.json']).then(function (d) {
    META = d[0];
    return leagueClubs().then(function () { return d; });
  }).then(function (d) {
    PLAYERS = FB.rows(d[1]);
    BYID = {};
    PLAYERS.forEach(function (p) { BYID[String(p.id)] = p; });
    return !!(META && PLAYERS.length);
  });
}
function followedLeagues() {
  var comps = (META || {}).comps || {};
  return Object.keys(comps).filter(function (s) { return comps[s].kind === 'league' && FB.comp(s) && FB.comp(s).ok; });
}
/* Clubs with a value/club file: the followed leagues' current clubs (teams.json). */
function leagueClubs() {
  if (LEAGUE_CLUBS) return Promise.resolve(LEAGUE_CLUBS);
  var lgs = followedLeagues();
  return Promise.all(lgs.map(function (s) { return FB.compFile(s, 'teams'); })).then(function (docs) {
    var list = [];
    docs.forEach(function (d, i) {
      var t = (d || {}).teams || {};
      Object.keys(t).forEach(function (n) { if (!t[n].team_id) return; if (t[n].crest) CRESTS[String(t[n].team_id)] = 1; list.push({ id: t[n].team_id, name: n, league: lgs[i] }); });
    });
    list.sort(function (a, b) { return a.name.localeCompare(b.name); });
    var lc = { list: list, byId: {} };
    list.forEach(function (c) { lc.byId[String(c.id)] = c; });
    if (META) LEAGUE_CLUBS = lc;      // keep only a list built from the value meta's leagues
    return lc;
  });
}
function clubFile(tid) {
  if (!tid || !LEAGUE_CLUBS || !LEAGUE_CLUBS.byId[String(tid)]) return Promise.resolve(null);
  return FB.load('value/club/' + tid + '.json');
}

function head(tab) {
  return FB.pageHead('Value & Transfers', tab === 'simulator' ? 'Transfer simulator' : tab === 'transfers' ? 'Transfers' : tab === 'budgets' ? 'Transfer budgets' : tab === 'method' ? 'How player value is made' : tab === 'positions' ? 'The best at each position' : 'Player value',
    'Every player\'s minutes measured in goals above a replacement-level player, on one scale across competitions with the pooled model; fair fees and budgets fitted on real transfers. <a href="#/model/methodology/value">Methodology →</a>') +
    FB.subnav(TABS.map(function (t) { return ['#/value' + (t[0] ? '/' + t[0] : ''), t[1], t[0] || 'players']; }), tab || 'players', 'Value views');
}
function missing(el) { el.insertAdjacentHTML('beforeend', FB.empty('Not built yet', 'The value payloads (data/value/) arrive with the next hourly build.')); }

FB.route('value', function (el, p) {
  var tab = p.tab || 'players';
  if (TABS.every(function (t) { return (t[0] || 'players') !== tab; })) tab = 'players';
  el.innerHTML = head(tab) + '<div id="va-body">' + FB.loading('lines', 6) + '</div>';
  var q = FB.merge(p.query || {}, {});
  return loadCore().then(function (ok) {
    if (!FB.alive(el)) return;
    var body = el.querySelector('#va-body');
    if (!ok) { body.innerHTML = ''; missing(body); return; }
    if (tab === 'positions') return drawPositions(el, body, q);
    if (tab === 'transfers') return drawTransfers(el, body, q);
    if (tab === 'simulator') return drawSimulator(el, body, q);
    if (tab === 'budgets') return drawBudgets(el, body, q);
    if (tab === 'method') return drawMethod(el, body);
    return drawPlayers(el, body, q);
  });
});

// ══ players ═════════════════════════════════════════════════════════════

function validationLine(m) {
  var v = (m.validation || {}).r2 || {};
  var x = v.xgd || {}, g = v.gd || {}, rel = m.reliability || {};
  if (!x.value) return '';
  return 'On ' + intl((m.validation || {}).n_test) + ' matches it had not seen, the line-ups\' value explained ' + pct(x.value, 1) +
    ' of the variance in non-penalty xG difference (Sofascore rating alone ' + pct(x.rating, 1) + ', each team\'s own form ' + pct(x.team, 1) + ') and ' +
    pct(g.value, 1) + ' of goal difference.' + (rel.value_r ? ' Split by odd and even matches, a player\'s value correlates ' + num(rel.value_r, 2) + ' with itself (rating ' + num(rel.rating_r, 2) + ').' : '');
}

function needLines() {
  if (LINES) return Promise.resolve(LINES);
  return Promise.all([FB.load('value/lines.json'), FB.clubsIndex()]).then(function (d) { LINES = FB.rows(d[0]); return LINES; });
}

/* This season's lines (lines.json: one per player per competition) for one scope: a competition's own lines, or one
   row per player summing his lines over every competition, club competitions or national-team football (minutes, GAR
   and PAR add up; GAR/90 is their ratio; rating and the components are minutes-weighted; the percentile is against
   the same unit among the rows shown with 900+ minutes). A merged duplicate id counts as the person. */
var POOLED = { '': 'All competitions', club: 'Club competitions', intl: 'National team' };
function seasonLines(q) {
  var scopeOf = function (slug) { var c = FB.comp(slug) || {}; return c.scope || (FB.kindOf(slug) === 'international' ? 'international' : 'club'); };
  var pid = function (id) { return FB.personId(id); };
  var line = function (l) {
    var pl = BYID[pid(l.id)] || BYID[String(l.id)] || {};
    return { id: pid(l.id), name: pl.name || ('#' + l.id), age: pl.age, comp: l.comp, tid: l.tid || pl.tid, club: !l.tid || l.tid === pl.tid ? pl.club : FB.clubName(l.tid),
      role: l.role, min: l.min, gar90: l.gar90, gar: l.gar, par: l.par, pct: l.pct, prev90: l.prev90, rt: l.rt, c: l.c, fvi: pl.fvi, proj: pl.proj, mv: pl.mv, v2: pl.v2 };
  };
  if (!(q.c in POOLED)) return (LINES || []).filter(function (l) { return l.comp === q.c; }).map(line);
  var by = {}, order = [];
  (LINES || []).forEach(function (l) {
    var sc = scopeOf(l.comp);
    if ((q.c === 'club' && sc === 'international') || (q.c === 'intl' && sc !== 'international') || !has(l.gar90)) return;
    var r = line(l), k = r.id, a = by[k];
    if (!a) { a = by[k] = { rows: [] }; order.push(k); }
    a.rows.push(r);
  });
  var out = order.map(function (k) {
    var rs = by[k].rows.slice().sort(function (x, y) { return (y.min || 0) - (x.min || 0); });
    var main = rs[0], pl = BYID[k] || {};
    var min = 0, gar = 0, par = 0, rw = 0, rm = 0, pw = 0, pm = 0, comps = [];
    rs.forEach(function (r) {
      min += r.min || 0; gar += r.gar || 0; par += r.par || 0;
      if (has(r.rt)) { rw += r.rt * r.min; rm += r.min; }
      if (has(r.prev90)) { pw += r.prev90 * r.min; pm += r.min; }
      comps.push(r.comp);
    });
    var c = null;
    rs.forEach(function (r) { if (!r.c) return; if (!c) c = r.c.map(function () { return 0; }); r.c.forEach(function (v, i) { c[i] += (v || 0) * r.min / Math.max(min, 1); }); });
    return { id: k, name: main.name, age: main.age, comp: main.comp, comps: comps, tid: q.c === 'intl' ? main.tid : (pl.tid || main.tid), club: q.c === 'intl' ? FB.clubName(main.tid, main.club) : (pl.club || main.club),
      role: pl.role || main.role, min: min, gar90: min ? gar * 90 / min : null, gar: gar, par: par, pct: null, prev90: pm ? pw / pm : null, rt: rm ? rw / rm : null, c: c,
      fvi: main.fvi, proj: main.proj, mv: main.mv, v2: main.v2, mix: rs.map(function (r) { return FB.compName(r.comp, true) + ' ' + Math.round(r.min) + '\''; }).join(' · ') };
  });
  var pools = {};
  out.forEach(function (r) { if (r.min >= 900 && has(r.gar90)) (pools[UNIT_OF[r.role] || 'MID'] = pools[UNIT_OF[r.role] || 'MID'] || []).push(r.gar90); });
  Object.keys(pools).forEach(function (u) { pools[u].sort(function (a, b) { return a - b; }); });
  out.forEach(function (r) {
    var vals = pools[UNIT_OF[r.role] || 'MID'];
    if (r.min < 900 || !vals || vals.length < 5) return;
    var lo = 0; while (lo < vals.length && vals[lo] < r.gar90) lo++;
    var up = lo; while (up < vals.length && vals[up] === r.gar90) up++;
    r.pct = Math.round(100 * (lo + 0.5 * (up - lo)) / vals.length);
  });
  return out;
}

/* The rows of the current view, filtered: last 12 months (players.json) or this season (lines.json). */
function valueRows(q) {
  var season = q.v === 'season';
  var comps = (META || {}).comps || {};
  var pooled = season && (q.c || '') in POOLED;
  var min = has(q.min) && q.min !== '' ? Number(q.min) : (season ? (pooled ? 450 : ((comps[q.c] || {}).floor || 270)) : 900);
  var qn = q.q ? norm(q.q) : '';
  var tierOf = function (slug) { return (comps[slug] || {}).tier || ''; };
  var rows;
  if (season) {
    rows = seasonLines(FB.merge(q, { c: q.c || '' }));
  } else {
    rows = PLAYERS.filter(function (pl) { return (pl.min || 0) > 0; }).map(function (pl) {
      return { id: pl.id, name: pl.name, age: pl.age, comp: pl.league, tid: pl.tid, club: pl.club, role: pl.role, min: pl.min, gar90: pl.gar90, gar: pl.gar, par: pl.par,
        pct: pl.pct, proj: pl.proj, fvi: pl.fvi, mv: pl.mv, rt: pl.rt, c: pl.c, free: pl.free, v2: pl.v2, v2lo: pl.v2lo, v2hi: pl.v2hi, fee: pl.fee, feelo: pl.feelo, feehi: pl.feehi, until: pl.until };
    });
  }
  return rows.filter(function (r) {
    return (r.min || 0) >= min && has(r.gar90) && (pooled || !q.c || r.comp === q.c) && (!q.t || tierOf(r.comp) === q.t) && (!q.club || String(r.tid) === String(q.club)) &&
      (!q.r || r.role === q.r || (q.r.length > 2 && UNIT_OF[r.role] === q.r)) && (!qn || norm(r.name).indexOf(qn) >= 0);
  });
}

function filterBar(q, withRole) {
  var season = q.v === 'season';
  var comps = (META || {}).comps || {};
  var all = season ? (LINES || []) : PLAYERS;
  var slugs = {};
  all.forEach(function (r) { var s = season ? r.comp : r.league; if (s) slugs[s] = 1; });
  var compOpts = Object.keys(slugs).map(function (s) { return [s, compName(s), (comps[s] || {}).kind === 'league' ? 0 : 1]; })
    .sort(function (a, b) { return a[2] - b[2] || a[1].localeCompare(b[1]); });
  var base = valueRows(FB.merge(q, { club: '', r: '', q: '' }));
  var clubs = {};
  base.forEach(function (r) { if (r.tid && r.club) clubs[r.tid] = r.club; });
  var clubOpts = Object.keys(clubs).map(function (t) { return [t, clubs[t]]; }).sort(function (a, b) { return a[1].localeCompare(b[1]); });
  var minDefault = season ? ((q.c || '') in POOLED ? 450 : ((comps[q.c] || {}).floor || 270)) : 900;
  var roles = ROLE_ORDER.filter(function (r) { return PLAYERS.some(function (pl) { return pl.role === r; }); });
  return FB.toolbar([
    FB.field('Window', FB.seg('va-v', [['', 'Last 12 months'], ['season', 'This season']], season ? 'season' : '', 'Window')),
    FB.field(season ? 'Competitions' : 'League', FB.select('va-c', (season ? [['', 'All competitions (one row per player)'], ['club', 'Club competitions'], ['intl', 'National team']] : [['', 'All leagues']])
      .concat(season ? [{ group: 'One competition', items: compOpts.map(function (o) { return [o[0], o[1]]; }) }] : compOpts.map(function (o) { return [o[0], o[1]]; })), q.c || '', 'Competition')),
    FB.field('Tier', FB.select('va-t', [['', 'Every tier']].concat(((META || {}).tiers || []).map(function (t) { return [t, t]; })), q.t || '', 'Tier')),
    FB.field('Club', FB.select('va-club', [['', 'Every club']].concat(clubOpts), q.club || '', 'Club', 'fb-va-wide')),
    withRole ? FB.field('Position', FB.select('va-r', [['', 'Every position']].concat(roles.map(function (r) { return [r, roleLabel(r)]; })), q.r || '', 'Position')) : '',
    FB.field('Min. minutes', '<input class="qk-input fb-va-num" type="number" id="va-min" min="0" step="90" value="' + esc(has(q.min) ? q.min : minDefault) + '">'),
    FB.field('Player', '<input class="qk-input" type="search" id="va-q" placeholder="Find a player" value="' + esc(q.q || '') + '">')
  ], 'fb-va-filters');
}
function wireFilters(root, q, redraw) {
  FB.wireSeg(root, 'va-v', function (v) { q = FB.setQuery({ v: v || null, c: null, min: null, club: null }); redraw(q); });
  [['va-c', 'c'], ['va-t', 't'], ['va-club', 'club'], ['va-r', 'r']].forEach(function (x) {
    var s = root.querySelector('#' + x[0]);
    if (s) s.addEventListener('change', function () {
      var patch = {}; patch[x[1]] = s.value || null;
      if (x[1] === 'c' || x[1] === 't') patch.club = null;
      if (x[1] === 'c') patch.min = null;
      q = FB.setQuery(patch); redraw(q);
    });
  });
  [['va-min', 'min'], ['va-q', 'q']].forEach(function (x) {
    var inp = root.querySelector('#' + x[0]), t = null;
    if (inp) inp.addEventListener('input', function () { clearTimeout(t); t = setTimeout(function () { var patch = {}; patch[x[1]] = inp.value || null; q = FB.setQuery(patch); redraw(q, true); }, 300); });
  });
}

function drawPlayers(el, body, q) {
  var m = META;
  var r2 = ((m.validation || {}).r2 || {}).xgd || {};
  var cv = ((((m.fee || {}).validation) || {}).cv || {}).model || {};
  body.innerHTML = FB.kpis([
    FB.kpi('Players valued', intl((m.counts || {}).players), { sub: intl((m.counts || {}).regulars) + ' regulars (900+ min in 12 months)' }),
    FB.kpi('Matches fitted', intl((m.model || {}).fit_matches), { sub: 'club matches with both line-ups' }),
    FB.kpi('Held-out fit', r2.value ? pct(r2.value, 1) : '—', { signal: true, sub: 'of xG difference explained · rating ' + (r2.rating ? pct(r2.rating, 1) : '—'), tip: 'Walk-forward R² of next matches\' non-penalty xG difference, against a home-advantage-only baseline.' }),
    FB.kpi('Fee model', cv.error_factor ? '×' + num(cv.error_factor, 2) : '—', { sub: cv.spearman ? 'typical error · rank corr. ' + num(cv.spearman, 2) : 'not fitted', tip: 'Out-of-sample typical error of the fair fee against real published fees.' }),
    FB.kpi('Updated', esc(FB.fmtDate(m.updated_at)), { text: true, sub: 'rebuilt every hour' })
  ]) +
    '<div class="fb-mt">' + FB.note('<b>GAR/90</b> is the goals a player adds per 90 minutes over a replacement-level player in the same role, the kind a club could sign cheaply. +0.30 is about one extra goal of difference every three matches. A <b>held-out fit</b> of ' + (r2.value ? pct(r2.value, 0) : '—') + ' sounds low, but one match is noisy and a player is one of eleven.') + '</div>' +
    '<div id="va-filter-card" class="fb-mt">' + FB.card('', '', '<div id="va-filters"></div><p class="fb-cap" id="va-note"></p>') + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Value against age', 'GAR/90 of the players shown (top 200) by age; colour is the position. Click a dot for the player.', FB.chartBox('va-sc-age', 340, 'Value per 90 by age') + roleLegend(), { span: 6 }) +
      FB.card('Our value against Sofascore\'s', 'Valuation v2 (points above replacement over four seasons) against Sofascore\'s market value (log scale), for reference.', FB.chartBox('va-sc-mv', 340, 'Our value against Sofascore market value') + roleLegend(), { span: 6, id: 'va-mv-card' })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.card('Leaderboard', 'Goals above replacement per 90; the cell colour is the percentile among peers in the same role (blue low, red high). ' + esc(HONEST), '<div id="va-table"></div>', { flush: true }) + '</div>' +
    '<p class="fb-cap">' + esc(validationLine(m)) + ' <a href="#/value/method">The weights and checks →</a></p>';
  var redraw = function (nq, keepInputs) {
    q = nq;
    var go = function () {
      if (!FB.alive(el)) return;
      if (!keepInputs) { el.querySelector('#va-filters').innerHTML = filterBar(q, true); wireFilters(el, q, redraw); }
      drawPlayersBody(el, q);
    };
    if (q.v === 'season' && !LINES) { FB.set('va-table', FB.loading('lines', 6)); needLines().then(go); } else go();
  };
  redraw(q);
}

function drawPlayersBody(el, q) {
  var season = q.v === 'season';
  var rows = valueRows(q).sort(function (a, b) { return (b.gar90 || 0) - (a.gar90 || 0); });
  var shown = rows.slice(0, 150);
  FB.set('va-note', intl(rows.length) + ' players' + (rows.length > shown.length ? ' (the top ' + shown.length + ' shown)' : '') + ' · ' +
    (season ? ((q.c || '') in POOLED ? 'this season, one row per player: lines summed over ' + (q.c === 'club' ? 'club competitions' : q.c === 'intl' ? 'national-team football' : 'every competition') + '; percentiles within the position group among the players shown with 900+ minutes; trend against last season, minutes-weighted.'
      : 'this season\'s lines in ' + FB.compName(q.c) + '; percentiles within the competition and position group over its minutes floor; trend against last season in the same competition.')
      : 'club football over the last 12 months, every competition; percentiles among regulars (900+ minutes) in the same role.'));
  var cols = [
    { key: 'name', label: 'Player', type: 'entity', sub: 'freeTxt', href: function (r) { return FB.href.player(r.id); } },
    { key: 'role', label: 'Pos', fmt: function (v) { return roleBadge(v); } },
    { key: 'club', label: 'Club', fmt: function (v, r) { return clink(r.tid, v); } },
    { key: 'comp', label: season ? 'Competition' : 'League', fmt: function (v, r) { return r.mix && r.comps && r.comps.length > 1 ? '<span class="qk-muted fb-lb-mix">' + esc(r.mix) + '</span>' : v ? FB.compLink(v, { short: true }) : '—'; } },
    { key: 'age', label: 'Age', num: true },
    { key: 'min', label: 'Min', num: true },
    { key: 'gar90', label: 'GAR/90', type: 'pctl', pctl: 'pct', tip: 'Goals above replacement per 90 minutes; the cell colour is the percentile among peers in the same role', fmt: function (v) { return '<b>' + g2(v) + '</b>'; } },
    { key: 'gar', label: 'GAR', num: true, tip: 'Goals above replacement in these minutes', fmt: function (v) { return has(v) ? signed(v, 1) : '—'; } },
    { key: 'par', label: 'PAR', num: true, tip: 'Points above replacement: GAR times the points a goal of goal difference is worth', fmt: function (v) { return has(v) ? signed(v, 1) : '—'; } }
  ];
  if (season) cols.push({ key: 'trend', label: 'Trend', num: true, tip: 'GAR/90 change against last season in the same competition (450+ minutes then)', fmt: function (v, r) { return has(r.prev90) ? FB.deltaHTML(r.gar90 - r.prev90, 2) : '—'; } });
  else cols = cols.concat([
    { key: 'proj', label: 'Proj.', num: true, tip: 'Projected GAR/90: shrunk toward replacement by 900 minutes', fmt: function (v) { return g2(v); } },
    { key: 'v2', label: 'Value', num: true, tip: 'Valuation v2: expected points above replacement over the next four seasons, with its 10-90% band', fmt: function (v, r) { return has(v) ? '<span data-tip="10-90%: ' + num(r.v2lo, 1) + ' to ' + num(r.v2hi, 1) + ' points">' + num(v, 1) + '</span>' : '—'; } },
    feeOn() ? { key: 'fee', label: 'Fair fee', num: true, tip: 'The fee model fitted on real fees: what a club like the player\'s own would pay', fmt: function (v, r) { return has(v) ? '<span data-tip="Middle half: ' + esc(moneyRange(r.feelo, r.feehi)) + '">' + money(v) + '</span>' : '—'; } }
      : { key: 'fvi', label: 'FVI', num: true, tip: 'Fair value index: 100 = the median regular of the top five leagues; not euros' },
    { key: 'mv', label: 'Sofascore value', num: true, tip: 'Sofascore\'s proposed market value, for reference', fmt: function (v) { return money(v); } }
  ]);
  cols.push({ key: 'why', label: 'Why', sort: false, fmt: function (v, r) { return drivers(r.c); } });
  cols.push({ key: 'sim', label: '', sort: false, fmt: function (v, r) { return '<a class="fb-link fb-va-sim" href="#/value/simulator?p=' + esc(r.id) + '">Simulate →</a>'; } });
  shown.forEach(function (r) { r.trend = has(r.prev90) ? r.gar90 - r.prev90 : null; r.freeTxt = r.free ? 'no club' : ''; });
  var tnode = document.getElementById('va-table');
  if (tnode) QK.leaderboard(tnode, { columns: cols, rows: shown, rank: true, dense: true, maxHeight: 640, caption: 'Player value leaderboard' });
  if (!shown.length) FB.set('va-table', FB.empty('No player clears the filters', 'Lower the minutes or widen the filters.'));
  /* charts */
  var top = rows.slice(0, 200);
  var c1 = el.querySelector('#va-sc-age');
  if (c1) {
    if (top.filter(function (r) { return has(r.age); }).length < 3) { c1.style.height = 'auto'; c1.innerHTML = FB.muted('Not enough players for a chart.'); }
    else QKC.scatter(c1, {
      points: top.filter(function (r) { return has(r.age); }).map(function (r) { return { x: r.age, y: r.gar90, name: r.name + ' · ' + (r.club || '') + ' · ' + r.role, color: roleHex(r.role), size: 6 + Math.min(14, Math.sqrt(r.min || 0) / 6), href: FB.href.player(r.id), label: FB.surname(r.name) }; }),
      xName: 'Age (years)', yName: 'GAR per 90', xFmt: function (v) { return num(v, 0); }, yFmt: function (v) { return signed(v, 2); }, labelTop: 8, label: 'Value per 90 by age'
    });
  }
  var c2 = el.querySelector('#va-sc-mv');
  var mvRows = season ? [] : top.filter(function (r) { return has(r.mv) && r.mv > 0 && has(r.v2); });
  if (c2) {
    if (mvRows.length < 3) { c2.style.height = 'auto'; c2.innerHTML = FB.muted(season ? 'Sofascore\'s values are compared on the last-12-months view.' : 'Too few Sofascore values under these filters.'); }
    else QKC.scatter(c2, {
      points: mvRows.map(function (r) { return { x: Math.log10(r.mv), y: r.v2, name: r.name + ' · ' + money(r.mv), color: roleHex(r.role), size: 9, href: FB.href.player(r.id), label: FB.surname(r.name) }; }),
      xName: 'Sofascore market value (log scale)', yName: 'Value v2 (pts)', xFmt: function (v) { return money(Math.pow(10, v)); }, yFmt: function (v) { return num(v, 1); }, labelTop: 8,
      quadrants: ['Underrated', 'Stars', '', 'Valued high'], label: 'Our value against Sofascore market value'
    });
  }
}

// ══ best at each position ═══════════════════════════════════════════════

function drawPositions(el, body, q) {
  var role = q.r && MAIN_ROLES.indexOf(q.r) >= 0 ? q.r : 'ST';
  body.innerHTML = FB.card('', '', '<div id="va-filters"></div><p class="fb-cap">The top eight in each role under the filters; roles come from the starting formations. Percentile chips are among regulars in the role.</p>') +
    '<div class="fb-mt">' + FB.card('Top fifteen', 'GAR/90 in one role under the filters.', '<div class="fb-toolbar" id="va-role-pick"></div>' + FB.chartBox('va-role-chart', 440, 'Top players in the role'), {}) + '</div>' +
    '<div class="fb-va-best fb-mt" id="va-best"></div>';
  var redraw = function (nq, keep) {
    q = nq;
    var go = function () {
      if (!FB.alive(el)) return;
      if (!keep) { el.querySelector('#va-filters').innerHTML = filterBar(q, false); wireFilters(el, q, redraw); }
      var pool = valueRows(FB.merge(q, { r: '' }));
      el.querySelector('#va-best').innerHTML = MAIN_ROLES.map(function (r) {
        var top = pool.filter(function (x) { return x.role === r; }).sort(function (a, b) { return b.gar90 - a.gar90; }).slice(0, 8);
        var mx = top.length ? Math.max(0.01, top[0].gar90) : 1;
        return '<section class="qk-card fb-va-bestc" style="--k:' + roleColor(r) + '"><div class="qk-card-head"><div class="fb-card-titles"><h3 class="qk-card-title">' + roleBadge(r) + ' ' + esc(roleLabel(r)) + '</h3></div></div><div class="qk-card-body">' +
          (top.length ? '<ol class="fb-va-list">' + top.map(function (x) {
            return '<li><div class="fb-va-li-top"><span class="fb-va-li-n">' + plink(x.id, x.name) + '</span><b class="fb-num">' + g2(x.gar90) + '</b>' + FB.pctl(x.pct) + '</div>' +
              '<span class="fb-va-bar"><i style="width:' + Math.max(2, x.gar90 / mx * 100).toFixed(0) + '%"></i></span>' +
              '<div class="fb-va-li-sub">' + esc([x.club, compName(x.comp), has(x.age) ? x.age + ' y' : '', intl(x.min) + ' min'].filter(Boolean).join(' · ')) + '</div>' +
              '<div class="fb-va-li-why">' + drivers(x.c, 3) + '</div></li>';
          }).join('') + '</ol>' : FB.muted('Nobody clears the filters.')) + '</div></section>';
      }).join('');
      drawRole();
    };
    var drawRole = function () {
      var pick = el.querySelector('#va-role-pick');
      pick.innerHTML = FB.seg('va-role', MAIN_ROLES.map(function (r) { return [r, r]; }), role, 'Role');
      FB.wireSeg(pick, 'va-role', function (v) { role = v; drawRole(); });
      var pool = valueRows(FB.merge(q, { r: '' })).filter(function (x) { return x.role === role; }).sort(function (a, b) { return b.gar90 - a.gar90; }).slice(0, 15);
      var box = el.querySelector('#va-role-chart');
      if (!pool.length) { box.style.height = 'auto'; box.innerHTML = FB.muted('Nobody clears the filters.'); return; }
      box.style.height = '';
      QKC.bar(box, {
        horizontal: true, labels: true, labelWidth: 140, fmt: function (v) { return signed(v, 2); }, valName: 'GAR per 90', catName: 'Player',
        cats: pool.map(function (x) { return x.name + ' · ' + (x.club || ''); }), series: [{ name: 'GAR/90', data: pool.map(function (x) { return Math.round(x.gar90 * 1000) / 1000; }) }],
        colors: pool.map(function () { return roleHex(role); }), hrefs: pool.map(function (x) { return FB.href.player(x.id); }), label: 'Top fifteen ' + roleLabel(role)
      });
    };
    if (q.v === 'season' && !LINES) needLines().then(go); else go();
  };
  redraw(q);
}

// ══ transfers ═══════════════════════════════════════════════════════════

var TRANSFERS = null;
function loadTransfers() {
  if (TRANSFERS) return Promise.resolve(TRANSFERS);
  return Promise.all([FB.load('value/transfers.json'), FB.clubsIndex()]).then(function (d) {
    var T = d[0];
    if (!T) return null;
    var deals = FB.rows(T), byKey = {};
    deals.forEach(function (x) { byKey[x.key] = x; });
    TRANSFERS = { T: T, deals: deals, byKey: byKey };
    return TRANSFERS;
  });
}
function covLine(T) {
  var cov = T.coverage || {};
  return intl(cov.transfers) + ' moves from Sofascore; ' + (cov.clubs_fetched || 0) + ' of ' + (cov.clubs_followed || 0) + ' followed clubs\' lists fetched (refreshed weekly, every two days in a window). ' +
    (T.fee_fitted ? 'Fair fees from the fee model.' : 'No fee model yet: grades use the minutes since only.');
}
function dealCols(winner) {
  var cols = [
    { key: 'date', label: 'Date', fmt: function (v) { return '<span class="fb-num">' + esc(v) + '</span>'; } },
    { key: 'name', label: 'Player', sticky: true, fmt: function (v, d) { return plink(d.pid, v) + ' ' + roleBadge(d.role) + (has(d.age) ? ' <span class="qk-muted fb-num">' + d.age + '</span>' : ''); } },
    { key: 'from_name', label: 'From', fmt: function (v, d) { return clink(d.from, v); } },
    { key: 'to_name', label: 'To', fmt: function (v, d) { return clink(d.to, v); } },
    { key: 'kind', label: 'Type', fmt: function (v) { return kindTag(v); } },
    { key: 'fee', label: 'Fee', num: true, fmt: function (v, d) { return d.kind === 'fee' ? money(v) : d.kind === 'free' ? 'Free' : '<span class="qk-muted">' + esc(d.fee_text && d.fee_text !== '-' ? d.fee_text : '—') + '</span>'; } },
    { key: 'fair', label: 'Fair fee', num: true, tip: 'Our fee model at the time of the move (cross-fitted: no deal is in the fit that values it)', fmt: function (v) { return money(v); } },
    { key: 'ratio', label: 'Fee/fair', num: true, tip: 'Under 100%: the buyer paid less than our fair fee', fmt: function (v) { return has(v) ? '<span class="' + (v <= 1 ? 'fb-up' : 'fb-down') + '">' + Math.round(v * 100) + '%</span>' : '—'; } },
    { key: 'post_min', label: 'Since', num: true, tip: 'Minutes for the new club since the move, and GAR/90 there', fmt: function (v, d) { return has(v) ? intl(v) + '\'' + (has(d.post_gar90) ? ' <span class="qk-muted">' + g2(d.post_gar90) + '</span>' : '') : '—'; } },
    { key: 'b_score', label: 'Buyer', tip: 'Grade for the buying club: fee against fair value, then the value delivered as the minutes come in', fmt: function (v, d) { return grade(d.b_grade, has(v) ? 'Buyer score ' + num(v, 2) : ''); } },
    { key: 's_score', label: 'Seller', tip: 'Grade for the selling club: fee received against fair value, less what the player has done since', fmt: function (v, d) { return grade(d.s_grade, has(v) ? 'Seller score ' + num(v, 2) : ''); } }
  ];
  if (winner) cols.push({ key: 'winner', label: 'Winner', fmt: function (v) { return v ? esc(v) : '—'; } });
  return cols;
}
function withRatio(list) { list.forEach(function (d) { d.ratio = d.kind === 'fee' && has(d.fair) && d.fee ? d.fee / d.fair : null; }); return list; }

function drawTransfers(el, body, q) {
  body.innerHTML = FB.loading('lines', 6);
  return loadTransfers().then(function (TR) {
    if (!FB.alive(el)) return;
    if (!TR || !TR.deals.length) { body.innerHTML = FB.empty('No transfers yet', 'The hourly task fills them from Sofascore.'); return; }
    var view = q.view === 'deals' || q.view === 'windows' ? q.view : 'feed';
    var views = [['feed', 'Latest transfers'], ['deals', 'Best and worst deals'], ['windows', 'Windows by league']];
    body.innerHTML = '<div class="qk-chips fb-va-views" role="group" aria-label="Transfer views">' + views.map(function (v) {
      return '<a class="qk-chip" href="#/value/transfers' + (v[0] === 'feed' ? '' : '?view=' + v[0]) + '" aria-pressed="' + (v[0] === view) + '">' + esc(v[1]) + '</a>';
    }).join('') + '</div><div id="va-tr" class="fb-mt"></div><p class="fb-cap">' + esc(covLine(TR.T)) + '</p>';
    var box = el.querySelector('#va-tr');
    if (view === 'deals') return drawDeals(el, box, TR);
    if (view === 'windows') return drawWindows(el, box, TR, q);
    return drawFeed(el, box, TR, q);
  });
}

function drawFeed(el, box, TR, q) {
  var deals = withRatio(TR.deals);
  var leagues = {};
  deals.forEach(function (d) { if (d.to_league) leagues[d.to_league] = 1; if (d.from_league) leagues[d.from_league] = 1; });
  var windows = {};
  deals.forEach(function (d) { if (d.window) windows[d.window] = 1; });
  var cutoff = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
  var year = deals.filter(function (d) { return d.date >= cutoff; });
  var fees = year.filter(function (d) { return d.kind === 'fee' && has(d.fee); });
  var spent = FB.sum(fees, 'fee');
  box.innerHTML = FB.kpis([
    FB.kpi('Moves, 12 months', intl(year.length), { sub: 'involving a followed club' }),
    FB.kpi('Fees, 12 months', money(spent), { sub: intl(fees.length) + ' published fees' }),
    FB.kpi('Record fee', fees.length ? money(Math.max.apply(null, fees.map(function (d) { return d.fee; }))) : '—', { sub: (fees.slice().sort(function (a, b) { return b.fee - a.fee; })[0] || {}).name || '' }),
    FB.kpi('Graded deals', intl(deals.filter(function (d) { return d.b_grade; }).length), { sub: 'buyer grades, A the best fifth' })
  ]) +
    '<div class="fb-mt">' + FB.card('The biggest fees of the last 12 months', 'What was paid (grey ring) against our fair fee at the time (blue).', FB.chartBox('va-fees', 420, 'Biggest fees against fair fees')) + '</div>' +
    '<div class="fb-mt">' + FB.card('Every move', 'Newest first; involving a followed club in the last 13 months.',
      FB.toolbar([
        FB.field('League', FB.select('tf-lg', [['', 'Every league']].concat(Object.keys(leagues).sort().map(function (l) { return [l, compName(l)]; })), q.lg || '', 'League')),
        FB.field('Type', FB.select('tf-k', [['', 'Every type']].concat(['fee', 'free', 'loan', 'undisclosed', 'loan_end', 'youth'].map(function (k) { return [k, KIND_LABEL[k]]; })), q.k || '', 'Type')),
        FB.field('Window', FB.select('tf-w', [['', 'Every window']].concat(Object.keys(windows).sort().reverse().map(function (w) { return [w, w]; })), q.w || '', 'Window')),
        FB.field('Player or club', '<input class="qk-input" type="search" id="tf-q" placeholder="Player or club" value="' + esc(q.q || '') + '">')
      ]) + '<p class="fb-cap" id="tf-note"></p><div id="tf-table"></div>') + '</div>';
  var top = fees.filter(function (d) { return has(d.fair); }).sort(function (a, b) { return b.fee - a.fee; }).slice(0, 12);
  var cbox = el.querySelector('#va-fees');
  if (top.length) {
    var mx = Math.max.apply(null, top.map(function (d) { return Math.max(d.fee, d.fair); }));
    QKC.dumbbell(cbox, { rows: top.map(function (d) { return { label: d.name + ' · ' + (d.to_name || ''), a: d.fair, b: d.fee, href: FB.href.player(d.pid), sub: (d.from_name || '') + ' → ' + (d.to_name || '') + ' · ' + d.date }; }),
      aName: 'Fair fee', bName: 'Fee paid', valName: 'Transfer fee', fmt: function (v) { return money(v); }, min: 0, max: mx * 1.05, labelWidth: 180, label: 'Biggest fees against fair fees' });
  } else { cbox.style.height = 'auto'; cbox.innerHTML = FB.muted('No published fee with a fair fee in the last 12 months.'); }
  var draw = function () {
    var qn = q.q ? norm(q.q) : '';
    var list = deals.filter(function (d) {
      return (!q.lg || d.to_league === q.lg || d.from_league === q.lg) && (!q.k || d.kind === q.k) && (!q.w || d.window === q.w) &&
        (!qn || norm((d.name || '') + ' ' + (d.from_name || '') + ' ' + (d.to_name || '')).indexOf(qn) >= 0);
    });
    FB.set('tf-note', intl(list.length) + ' moves' + (list.length > 300 ? ' (the newest 300 shown; filter to see the rest)' : '') + '.');
    if (!list.length) { FB.set('tf-table', FB.empty('No transfer fits', 'Widen the filters.')); return; }
    FB.table('tf-table', dealCols(false), list.slice(0, 300), { maxHeight: 640, caption: 'Transfers' });
  };
  [['tf-lg', 'lg'], ['tf-k', 'k'], ['tf-w', 'w']].forEach(function (x) {
    var s = el.querySelector('#' + x[0]);
    if (s) s.addEventListener('change', function () { var p = {}; p[x[1]] = s.value || null; q = FB.setQuery(p); draw(); });
  });
  var inp = el.querySelector('#tf-q'), t = null;
  if (inp) inp.addEventListener('input', function () { clearTimeout(t); t = setTimeout(function () { q = FB.setQuery({ q: inp.value || null }); draw(); }, 300); });
  draw();
}

function drawDeals(el, box, TR) {
  withRatio(TR.deals);
  var best = (TR.T.best || []).map(function (k) { return TR.byKey[k]; }).filter(Boolean);
  var worst = (TR.T.worst || []).map(function (k) { return TR.byKey[k]; }).filter(Boolean);
  box.innerHTML = FB.grid(
    FB.card('Buyer scores', 'The best and worst deals of the last 12 months for the buying club (higher is better).', FB.chartBox('va-deal-chart', 460, 'Buyer scores of the best and worst deals'), { span: 12 })) +
    '<div class="fb-mt">' + FB.card('Best deals of the last 12 months', 'For the buying club: fee against fair value at the time, then the value delivered since.', '<div id="td-best"></div>', { flush: true }) + '</div>' +
    '<div class="fb-mt">' + FB.card('Worst deals of the last 12 months', '', '<div id="td-worst"></div>', { flush: true }) + '</div>' +
    '<p class="fb-cap">Grades are quintiles among the year\'s graded deals (A the best fifth). The fee part is log(fair fee / fee), so paying half the fair fee and paying double are equally far from fair; a free signing scores log((fair + €1m) / €1m). The value since the move counts in proportion to the player\'s minutes, fully from 1,800: GAR/90 for the new club (shrunk toward the projection at the time by 900 minutes) against that projection, plus the share of the minutes against 60%. Loans are graded on the minutes since alone, once there are 450.</p>';
  if (best.length) FB.table('td-best', dealCols(true), best, {}); else FB.set('td-best', FB.empty('Not enough graded deals yet'));
  if (worst.length) FB.table('td-worst', dealCols(true), worst, {}); else FB.set('td-worst', FB.empty('Not enough graded deals yet'));
  var rows = best.slice(0, 10).concat(worst.slice(0, 10)).filter(function (d) { return has(d.b_score); }).sort(function (a, b) { return b.b_score - a.b_score; });
  var c = el.querySelector('#va-deal-chart');
  if (rows.length) QKC.bar(c, { horizontal: true, diverging: true, labels: true, labelWidth: 170, fmt: function (v) { return signed(v, 2); },
    cats: rows.map(function (d) { return d.name + ' → ' + (d.to_name || ''); }), valName: 'Buyer score', series: [{ name: 'Buyer score', data: rows.map(function (d) { return Math.round(d.b_score * 100) / 100; }) }],
    hrefs: rows.map(function (d) { return FB.href.player(d.pid); }), label: 'Buyer scores' });
  else { c.style.height = 'auto'; c.innerHTML = FB.muted('No graded deals yet.'); }
}

function drawWindows(el, box, TR, q) {
  var W = TR.T.windows || {};
  var lgs = Object.keys(W).sort(function (a, b) { return compName(a).localeCompare(compName(b)); });
  if (!lgs.length) { box.innerHTML = FB.empty('No window summaries yet'); return; }
  var lg = q.lg && W[q.lg] ? q.lg : (W['premier-league'] ? 'premier-league' : lgs[0]);
  var ws = W[lg] || {};
  var keys = Object.keys(ws).sort();
  var nm = function (k) { var d = TR.byKey[k]; return d ? plink(d.pid, d.name) + ' <span class="qk-muted">' + (d.kind === 'fee' ? money(d.fee) : esc(KIND_LABEL[d.kind] || d.kind)) + '</span>' : ''; };
  box.innerHTML = FB.toolbar([FB.field('League', FB.select('tw-lg', lgs.map(function (l) { return [l, compName(l)]; }), lg, 'League'))]) +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Spending and sales by window', compName(lg) + ' · published fees only (undisclosed fees are counted, not summed).', FB.chartBox('tw-chart', 320, 'Spending and sales by window'), { span: 7 }) +
      FB.card('Net spend, latest window', 'Clubs\' published fees in, less fees out.', FB.chartBox('tw-net', 320, 'Net spend by club'), { span: 5 })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.card('Window by window', '', '<div id="tw-table"></div>', { flush: true }) + '</div>' +
    '<p class="fb-cap">Summer: May-October; winter: November-April. Windows before the last two rely on players\' transfer histories, which are still filling in, so older totals are incomplete.</p>';
  var s = el.querySelector('#tw-lg');
  if (s) s.addEventListener('change', function () { FB.setQuery({ lg: s.value }, true); });
  QKC.bar(el.querySelector('#tw-chart'), {
    cats: keys.map(function (k) { return ws[k].label || k; }), legend: true, fmt: function (v) { return money(v); }, valName: 'Transfer fees', catName: 'Transfer window',
    series: [{ name: 'Spent', data: keys.map(function (k) { return ws[k].spend || 0; }) }, { name: 'Sold', data: keys.map(function (k) { return ws[k].income || 0; }) }],
    label: 'Spending and sales by window'
  });
  var last = ws[keys[keys.length - 1]] || {};
  var net = {};
  (last.spenders || []).concat(last.sellers || []).forEach(function (c) { net[c[0]] = (c[1] || 0) - (c[2] || 0); });
  var nk = Object.keys(net).sort(function (a, b) { return net[b] - net[a]; });
  var nb = el.querySelector('#tw-net');
  if (nk.length) QKC.bar(nb, { horizontal: true, diverging: true, labels: true, labelWidth: 120, fmt: function (v) { return netText(v); },
    cats: nk.map(function (t) { return FB.clubName(t, '#' + t); }), valName: 'Net spend', series: [{ name: 'Net spend', data: nk.map(function (t) { return net[t]; }) }], hrefs: nk.map(function (t) { return FB.href.club(t); }), label: 'Net spend by club' });
  else { nb.style.height = 'auto'; nb.innerHTML = FB.muted('No published fees in the latest window.'); }
  var rows = keys.slice().reverse().map(function (k) { var x = ws[k]; return FB.merge(x, { key: k }); });
  FB.table('tw-table', [
    { key: 'key', label: 'Window', sticky: true, fmt: function (v, x) { return esc(x.label || v); } },
    { key: 'spend', label: 'Spent', num: true, fmt: function (v) { return money(v); } },
    { key: 'income', label: 'Sold', num: true, fmt: function (v) { return money(v); } },
    { key: 'net', label: 'Net', num: true, fmt: function (v) { return netText(v); } },
    { key: 'n_in', label: 'Signings', num: true, tip: 'Fee / free / loan / undisclosed', fmt: function (v, x) { return (x.n_fee_in || 0) + ' / ' + (x.free_in || 0) + ' / ' + (x.loans_in || 0) + ' / ' + (x.undisclosed_in || 0); } },
    { key: 'top', label: 'Biggest fees', sort: false, fmt: function (v) { return (v || []).slice(0, 3).map(nm).join('<br>'); } },
    { key: 'best', label: 'Best value', sort: false, fmt: function (v) { return (v || []).slice(0, 3).map(nm).join('<br>') || '—'; } },
    { key: 'spenders', label: 'Top net spenders', sort: false, fmt: function (v) { return (v || []).map(function (c) { return clink(c[0], FB.clubName(c[0], '#' + c[0])) + ' <span class="qk-muted fb-num">' + money((c[1] || 0) - (c[2] || 0)) + '</span>'; }).join('<br>') || '—'; } }
  ], rows, { dense: false });
}

// ══ simulator ═══════════════════════════════════════════════════════════

/* The fee model's fair fee for a player to a buyer: the published ridge on standardised features. [fee, lo, hi] or null. */
function fairFee(P, buyerXgd, sellerXgd) {
  var fm = ((META || {}).fee || {}).model;
  if (!fm || !P || !has(P.v2) || (P.min || 0) < 450) return null;
  var unit = UNIT_OF[P.role] || 'MID';
  var age = (has(P.age) ? P.age + 0.5 : 26) - 26;
  var sx = has(sellerXgd) ? sellerXgd : null, bx = has(buyerXgd) ? buyerXgd : null;
  var x = [Math.log(1 + Math.max(P.v2, 0)), P.proj || 0, age, age * age,
    unit === 'CB' ? 1 : 0, unit === 'FB' ? 1 : 0, unit === 'MID' ? 1 : 0, unit === 'ATT' ? 1 : 0, unit === 'ST' ? 1 : 0,
    sx === null ? fm.unknown_xgd : sx, sx === null ? 1 : 0, bx === null ? fm.unknown_xgd : bx, bx === null ? 1 : 0, Math.log(1 + (P.min || 0) / 90)];
  var lp = fm.intercept;
  for (var i = 0; i < x.length; i++) lp += ((x[i] - fm.mean[i]) / (fm.sd[i] || 1)) * fm.coef[i];
  var z = 0.6745 * (fm.sigma || 0.8);
  return [Math.exp(lp), Math.exp(lp - z), Math.exp(lp + z)];
}
function affordWord(fee, budget) {
  var b = (budget || {}).summer;
  if (!fee || !b || !has(b.hi)) return '';
  var w = fee <= b.hi ? 'within' : fee <= b.hi80 ? 'a stretch for' : 'beyond';
  return '<b class="' + (w === 'within' ? 'fb-up' : w === 'beyond' ? 'fb-down' : '') + '">' + esc(w) + '</b>';
}
function alloc(depth, slots) {
  var left = Math.max(slots || 1, 0) * 90, total = 0, mins = {};
  depth.slice().sort(function (a, b) { return (b.proj || 0) - (a.proj || 0); }).forEach(function (d) {
    var take = Math.max(0, Math.min(has(d.cap) ? d.cap : MINUTES_CAP, left));
    mins[d.id] = take; total += take * (d.proj || 0) / 90; left -= take;
  });
  return { value: total, mins: mins, spare: Math.max(left, 0) };
}
function unitOf(role) { return UNIT_OF[role] || 'MID'; }
function withCaps(club) {
  var tot = {};
  (club.units || []).forEach(function (u) { (u.depth || []).forEach(function (d) { tot[d.id] = (tot[d.id] || 0) + (d.min || 0); }); });
  return (club.units || []).map(function (u) {
    return FB.merge(u, { depth: (u.depth || []).map(function (d) { return FB.merge(d, { cap: tot[d.id] > 0 ? MINUTES_CAP * (d.min || 0) / tot[d.id] : (unitOf(d.role) === u.unit ? MINUTES_CAP : 0) }); }) });
  });
}
function clubDelta(club, add, remove) {
  var out = { delta: 0, units: [] };
  withCaps(club).forEach(function (u) {
    var before = alloc(u.depth || [], u.slots);
    var depth = (u.depth || []).filter(function (d) { return remove.indexOf(String(d.id)) < 0; });
    if (add && unitOf(add.role) === u.unit) depth = depth.filter(function (d) { return String(d.id) !== String(add.id); }).concat([{ id: String(add.id), name: add.name, role: add.role, proj: add.proj || 0, min: 0, cap: MINUTES_CAP, isNew: true }]);
    var touched = depth.length !== (u.depth || []).length || depth.some(function (d) { return d.isNew; });
    if (!touched) return;
    var after = alloc(depth, u.slots);
    out.delta += after.value - before.value;
    out.units.push({ unit: u, before: before, after: after, depth: depth });
  });
  return out;
}
function interp(xs, ys, x) {
  if (!xs || !ys || !xs.length) return null;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  for (var i = 1; i < xs.length; i++) if (x <= xs[i]) { var t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]); return ys[i - 1] + t * (ys[i] - ys[i - 1]); }
  return ys[ys.length - 1];
}
function oddsRows(slug, teamName, delta, sens, probsDoc) {
  var probs = (((probsDoc || {}).teams) || []).filter(function (t) { return t.team === teamName; })[0] || null;
  var c = FB.comp(slug) || {};
  var curves = sens && sens.teams ? sens.teams[teamName] : null;
  if (!curves || !probs) return null;
  var shifts = sens.shifts || [];
  var out = [];
  var add = function (label, base, key, isPts) {
    var ys = curves[key];
    if (!ys || !has(base)) return;
    var diff = interp(shifts, ys, delta) - interp(shifts, ys, 0);
    var after = isPts ? base + diff : Math.min(Math.max(base + diff, 0), 1);
    out.push({ label: label, base: base, after: after, diff: after - base, pts: !!isPts });
  };
  var k = c.kind;
  if (k === 'liga') {
    add('Torneo champion', probs.p_title, 'p_title'); add('Copa Libertadores', probs.p_libertadores, 'band:libertadores');
    add('Copa Sudamericana', probs.p_sudamericana, 'band:sudamericana'); add('Relegation', probs.p_relegation, 'band:relegation');
  } else {
    add(k === 'conference' ? 'Supporters\' Shield' : k === 'playoff' ? 'Top of the table' : 'Title', probs.p_title, 'p_title');
    if (has(probs.p_cup)) add(k === 'conference' ? 'MLS Cup' : k === 'playoff' ? 'Liguilla title' : 'Play-off title', probs.p_cup, 'p_cup');
    if (has(probs.p_playoffs)) add('Play-offs', probs.p_playoffs, 'p_playoffs');
    (sens.bands || []).forEach(function (b) { var key = b.key.replace(/^band:/, ''); if (probs.bands && has(probs.bands[key])) add(b.label, probs.bands[key], b.key); });
  }
  add('Expected points', probs.exp_pts, 'exp_pts', true);
  return { rows: out, clamped: delta < shifts[0] || delta > shifts[shifts.length - 1], n: sens.n_sims, remaining: curves.remaining };
}
function oddsTableHTML(o) {
  if (!o) return FB.muted('No season chances for this club (its league is not simulated, or the season is over).');
  var bad = function (r) { return /relegation/i.test(r.label); };
  return '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th></th><th class="num">Now</th><th class="num">After</th><th class="num">Change</th></tr></thead><tbody>' +
    o.rows.map(function (r) {
      var tiny = Math.abs(r.diff) < (r.pts ? 0.05 : 0.0005);
      var cls = tiny ? 'qk-muted' : (bad(r) ? (r.diff > 0 ? 'fb-down' : 'fb-up') : (r.diff > 0 ? 'fb-up' : 'fb-down'));
      return '<tr><td>' + esc(r.label) + '</td><td class="num">' + (r.pts ? num(r.base, 1) : pct(r.base, 1)) + '</td><td class="num"><b>' + (r.pts ? num(r.after, 1) : pct(r.after, 1)) + '</b></td>' +
        '<td class="num"><span class="' + cls + '">' + (r.pts ? signed(r.diff, 1) : signed(r.diff * 100, 1) + ' pp') + '</span></td></tr>';
    }).join('') + '</tbody></table></div>' +
    '<p class="fb-cap">Changes in our chances in percentage points (pp), from re-running the season simulation with the club\'s strength shifted (' + intl(o.n) + ' runs per shift, common random numbers)' +
    (o.remaining ? '; ' + o.remaining + ' league matches left' : '') + '.' + (o.clamped ? ' The shift is beyond the simulated range, so the change stops at the end of that range.' : '') + '</p>';
}
function depthHTML(du) {
  var rows = du.depth.slice().sort(function (a, b) { return (du.after.mins[b.id] || 0) - (du.after.mins[a.id] || 0) || (b.proj || 0) - (a.proj || 0); });
  var gone = (du.unit.depth || []).filter(function (d) { return !du.depth.some(function (x) { return String(x.id) === String(d.id); }); }).map(function (d) { return FB.merge(d, { gone: true }); });
  return '<div class="fb-va-unit">' + esc(du.unit.label) + ' <span class="qk-muted">· ' + num(du.unit.slots, 1) + ' players a match</span></div>' +
    '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Player</th><th class="num">Proj. GAR/90</th><th class="num">Min before</th><th class="num">After</th></tr></thead><tbody>' +
    rows.concat(gone).map(function (d) {
      return '<tr class="' + (d.isNew ? 'fb-va-new' : d.gone ? 'fb-va-gone' : '') + '"><td>' + plink(d.id, d.name) + ' ' + roleBadge(d.role) + (d.isNew ? ' ' + FB.badge('in', 'accent') : d.gone ? ' ' + FB.badge('out') : '') + '</td>' +
        '<td class="num">' + g2(d.proj) + '</td><td class="num">' + (d.isNew ? '—' : Math.round(du.before.mins[d.id] || 0) + '\'') + '</td><td class="num">' + (d.gone ? '—' : Math.round(du.after.mins[d.id] || 0) + '\'') + '</td></tr>';
    }).join('') + '</tbody></table></div>' +
    (du.after.spare > 1 ? '<p class="fb-cap">' + Math.round(du.after.spare) + ' minutes a match left to a replacement-level player.</p>' : '');
}

/* A type-ahead picker: items [{n, w, sub(html), v}] -> onPick(item). */
function picker(id, placeholder, value) {
  return '<div class="fb-va-pick"><input class="qk-input" id="' + id + '" type="search" placeholder="' + esc(placeholder) + '" autocomplete="off" value="' + esc(value || '') + '" aria-label="' + esc(placeholder) + '"><ul class="fb-va-res" id="' + id + '-res" hidden></ul></div>';
}
function wirePicker(root, id, items, onPick) {
  var input = root.querySelector('#' + id), box = root.querySelector('#' + id + '-res');
  if (!input || !box) return;
  var hits = [];
  var show = function () {
    var n = norm(input.value.trim());
    if (n.length < 2) { box.hidden = true; return; }
    hits = items.filter(function (x) { return x._n.indexOf(n) >= 0; }).sort(function (a, b) { return (a._n.indexOf(n) === 0 ? 0 : 1) - (b._n.indexOf(n) === 0 ? 0 : 1) || (b.w || 0) - (a.w || 0); }).slice(0, 10);
    box.innerHTML = hits.length ? hits.map(function (x, i) { return '<li><button type="button" data-i="' + i + '">' + x.label + '</button></li>'; }).join('') : '<li class="fb-va-res-empty">No match.</li>';
    box.hidden = false;
  };
  items.forEach(function (x) { x._n = norm(x.n); });
  input.addEventListener('input', show);
  input.addEventListener('focus', show);
  input.addEventListener('keydown', function (e) { if (e.key === 'Escape') box.hidden = true; if (e.key === 'Enter' && hits[0]) { e.preventDefault(); box.hidden = true; onPick(hits[0]); } });
  box.addEventListener('click', function (e) { var b = e.target.closest('[data-i]'); if (b) { box.hidden = true; onPick(hits[Number(b.getAttribute('data-i'))]); } });
  document.addEventListener('click', function (e) { if (!e.target.closest('.fb-va-pick')) box.hidden = true; });
}

function playerCard(P) {
  return '<section class="qk-hero fb-va-hero" style="--tc:' + roleColor(P.role) + '"><div class="qk-hero-in">' +
    '<div class="qk-avatar" style="--tc:' + roleColor(P.role) + '">' + esc(FB.initials(P.name)) + '</div>' +
    '<div><div class="qk-kicker">' + roleBadge(P.role) + ' ' + esc(roleLabel(P.role)) + (has(P.age) ? ' · ' + P.age + ' years' : '') + (P.nat ? ' · ' + esc(P.nat) : '') + '</div>' +
    '<h2 class="fb-va-hero-n">' + plink(P.id, P.name) + '</h2><div class="qk-hero-meta"><span>' + (P.free ? 'No club (Sofascore lists no team)' : clink(P.tid, P.club)) + '</span>' + (P.league ? '<span>' + esc(compName(P.league)) + '</span>' : '') +
    (P.until ? '<span>Contract <b>' + esc(P.until) + '</b></span>' : '') + '</div></div>' +
    '<div class="qk-hero-stats">' +
    '<div class="qk-hero-stat"><div class="v">' + g2(P.gar90) + '</div><div class="l">GAR/90</div></div>' +
    '<div class="qk-hero-stat"><div class="v">' + g2(P.proj) + '</div><div class="l">Projected</div></div>' +
    '<div class="qk-hero-stat"><div class="v">' + (has(P.pct) ? Math.round(P.pct) : '—') + '</div><div class="l">Pctl</div></div>' +
    '<div class="qk-hero-stat"><div class="v">' + (has(P.v2) ? num(P.v2, 1) : '—') + '</div><div class="l">Value v2</div></div>' +
    (feeOn() ? '<div class="qk-hero-stat"><div class="v">' + money(P.fee) + '</div><div class="l">Fair fee</div></div>' : '') +
    '<div class="qk-hero-stat"><div class="v">' + money(P.mv) + '</div><div class="l">Sofascore value</div></div></div></div>' +
    (P.c ? '<p class="fb-cap fb-va-hero-why">Why: ' + drivers(P.c, 4) + ' <span class="qk-muted">(per 90, against the average ' + esc(roleLabel(P.role).toLowerCase()) + ')</span></p>' : '') + '</section>';
}

function drawSimulator(el, body, q) {
  body.innerHTML = FB.loading('lines', 5);
  return leagueClubs().then(function (LC) {
    if (!FB.alive(el)) return;
    var P = q.p ? BYID[String(q.p)] : null;
    var B = q.to ? LC.byId[String(q.to)] : null;
    body.innerHTML = FB.card('Pick a move', 'Put a player in another club\'s squad and see what the models say. Clubs: the twelve pooled leagues and Argentina.',
      '<div class="fb-va-picks">' + FB.field('Player', picker('tr-player', 'Search a player…', P ? P.name : '')) + FB.field('Buying club', picker('tr-club', 'Search a club…', B ? B.name : '')) +
      '<button type="button" class="qk-btn" id="tr-share">Copy link</button></div><p class="fb-cap">' + esc(HONEST) + '</p>') + '<div id="tr-body" class="fb-mt"></div>';
    var nav = function (patch) { FB.setQuery(patch, true); };
    wirePicker(el, 'tr-player', PLAYERS.filter(function (x) { return (x.min || 0) >= 90; }).map(function (x) {
      return { n: x.name, w: x.min, p: x, label: '<span class="fb-va-res-n">' + esc(x.name) + '</span> ' + roleBadge(x.role) + ' <span class="qk-muted">' + esc(x.club || 'no club') + ' · ' + g2(x.gar90) + '</span>' };
    }), function (x) { nav({ p: x.p.id }); });
    wirePicker(el, 'tr-club', LC.list.map(function (c) { return { n: c.name, w: 1, c: c, label: crest(c.id, c.name) + ' <span class="fb-va-res-n">' + esc(c.name) + '</span> <span class="qk-muted">' + esc(compName(c.league)) + '</span>' }; }),
      function (x) { nav({ to: x.c.id, out: null }); });
    var share = el.querySelector('#tr-share');
    if (share) share.addEventListener('click', function () {
      var url = location.href;
      var done = function () { share.textContent = 'Link copied'; setTimeout(function () { share.textContent = 'Copy link'; }, 1600); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, function () { window.prompt('Copy this link', url); });
      else window.prompt('Copy this link', url);
    });
    var tb = el.querySelector('#tr-body');
    if (!P) {
      var eg = PLAYERS.filter(function (x) { return (x.min || 0) >= 1800 && has(x.proj) && x.tid; }).sort(function (a, b) { return (b.gar90 || 0) - (a.gar90 || 0); })[0];
      var to = eg ? LC.list.filter(function (c) { return String(c.id) !== String(eg.tid); })[0] : null;
      tb.innerHTML = FB.empty('Pick a player and a buying club', eg && to ? 'For example, ' + eg.name + ' to ' + to.name + '.' : '') +
        (eg && to ? '<p class="fb-cap" style="text-align:center"><a href="#/value/simulator?p=' + esc(eg.id) + '&to=' + esc(to.id) + '">Try ' + esc(eg.name) + ' to ' + esc(to.name) + ' →</a></p>' : '');
      return;
    }
    if (!B) { tb.innerHTML = playerCard(P) + '<div class="fb-mt">' + FB.empty('Now pick the buying club', 'Any club in the twelve pooled leagues or Argentina.') + '</div>'; return; }
    tb.innerHTML = playerCard(P) + FB.loading('lines', 4);
    var sellerTid = P.free ? null : P.tid;
    return Promise.all([clubFile(B.id), clubFile(sellerTid)]).then(function (cf) {
      if (!FB.alive(el)) return;
      var BC = cf[0], SC = cf[1];
      if (!BC) { tb.innerHTML = playerCard(P) + FB.empty('No strengths-and-needs file for ' + B.name + ' yet'); return; }
      var leagues = [BC.league].concat(SC && SC.league !== BC.league ? [SC.league] : []);
      return Promise.all(leagues.map(function (s) { return FB.compFile(s, 'sensitivity'); }).concat(leagues.map(function (s) { return FB.compFile(s, 'probs'); }))).then(function (res) {
        if (!FB.alive(el)) return;
        var sens = {}, probs = {};
        leagues.forEach(function (s, i) { sens[s] = res[i]; probs[s] = res[leagues.length + i]; });
        drawSimResult(el, tb, P, BC, SC && String(SC.tid) !== String(BC.tid) ? SC : null, sens, probs, q);
      });
    });
  });
}

function drawSimResult(el, tb, P, B, S, sens, probs, q) {
  var out = String(q.out || '').split(',').filter(Boolean);
  if (String(P.tid) === String(B.tid)) { tb.innerHTML = playerCard(P) + '<div class="fb-mt">' + FB.empty(P.name + ' already plays for ' + B.name, 'Pick another club.') + '</div>'; return; }
  var bd = clubDelta(B, P, out);
  var sd = S ? clubDelta(S, null, [String(P.id)]) : null;
  var sB = sens[B.league] || {};
  var gdB = B.gd_per_delta || (((sB.teams || {})[B.name] || {}).gd_per_delta) || 1.3;
  var deltaB = bd.delta / gdB;
  var oB = oddsRows(B.league, B.name, deltaB, sB, probs[B.league]);
  var oS = null, deltaS = 0;
  if (S) { deltaS = sd.delta / (S.gd_per_delta || 1.3); oS = oddsRows(S.league, S.name, deltaS, sens[S.league] || {}, probs[S.league]); }
  var unitRow = bd.units.filter(function (u) { return u.unit.unit === unitOf(P.role); })[0];
  var pMins = unitRow ? unitRow.after.mins[String(P.id)] || 0 : 0;
  var role = pMins >= 70 ? 'would start' : pMins >= 30 ? 'would share the minutes' : pMins > 0 ? 'would be a back-up' : 'would not get minutes ahead of the current players';
  var ptsOf = function (o) { var r = o ? o.rows.filter(function (x) { return x.pts; })[0] : null; return r ? r.diff : null; };
  var verdict = function (name, d, pts, seller) {
    if (Math.abs(d) < 0.005) return '<b>' + esc(name) + '</b>: no change now' + (seller ? '.' : ' — ' + esc(P.name) + ' ' + role + '.');
    var word = d > 0 ? (d > 0.05 ? 'stronger now' : 'a marginal gain now') : (d < -0.05 ? 'weaker now' : 'a marginal loss now');
    return '<b>' + esc(name) + '</b>: <span class="' + (d > 0 ? 'fb-up' : 'fb-down') + '">' + word + '</span> (' + signed(d, 2) + ' goals of xG difference a match' + (has(pts) ? ', ' + signed(pts, 1) + ' expected points over the rest of the season' : '') + ')' + (seller ? '.' : '; ' + esc(P.name) + ' ' + role + ' (' + Math.round(pMins) + '\' a match).');
  };
  var age = P.age;
  var longTerm = !has(age) ? '' : age <= 23 ? 'Long term: players of ' + age + ' still improve on the ageing curve, and the value counts four seasons.' :
    age >= 31 ? 'Long term: at ' + age + ' the ageing curve and career length both shorten the value.' : 'Long term: at ' + age + ' roughly at peak on the ageing curve.';
  var win = ((META || {}).windows || {})[B.league];
  var winText = win ? (win.open ? 'The ' + compName(B.league) + ' window is open (usually until ' + win.until + ').' : 'The ' + compName(B.league) + ' window is closed; the next usually opens ' + (win.next || '') + '.') + ' Typical dates; each association sets its own.' : '';
  var ff = fairFee(P, (B.pool || {}).xgd, S && S.pool ? S.pool.xgd : null);
  var bud = B.budget || {}, bs = bud.summer || {}, bn = bud.next || {};
  var seen = {};
  var outOpts = (B.units || []).map(function (u) {
    return (u.depth || []).filter(function (d) { if (seen[d.id]) return false; seen[d.id] = 1; return true; }).map(function (d) {
      return '<label class="fb-va-out"><input type="checkbox" data-out="' + esc(d.id) + '"' + (out.indexOf(String(d.id)) >= 0 ? ' checked' : '') + '> ' + esc(d.name) + ' ' + roleBadge(d.role) + '</label>';
    }).join('');
  }).join('');
  var pts = ptsOf(oB);
  var h = playerCard(P) +
    '<div class="fb-mt">' + FB.kpis([
      FB.kpi('Goals a match, ' + B.name, signed(bd.delta, 3), { signal: true, sub: 'xG difference change, our model' }),
      FB.kpi('Expected points', has(pts) ? signed(pts, 1) : '—', { sub: 'rest of the season' }),
      FB.kpi('Minutes a match', Math.round(pMins) + '\'', { sub: role }),
      FB.kpi('Fair fee to ' + B.name, ff ? money(ff[0]) : '—', { sub: ff ? 'middle half ' + moneyRange(ff[1], ff[2]) : 'under 450 minutes or no fee model' }),
      FB.kpi('Summer budget', has(bs.mid) ? money(bs.mid) : '—', { sub: has(bs.lo) ? '25-75%: ' + moneyRange(bs.lo, bs.hi) : 'no estimate' })
    ]) + '</div>' +
    '<div class="fb-mt">' + FB.card('The verdict', esc(P.name) + ' to ' + esc(B.name) + (out.length ? ', ' + out.length + ' out' : ''),
      '<div class="fb-prose"><p>' + verdict(B.name, bd.delta, pts) + '</p>' +
      (S ? '<p>' + verdict(S.name, sd.delta, ptsOf(oS), true) + '</p>' : P.free ? '<p>No selling club: Sofascore lists the player without a team.</p>' : '<p>' + esc(P.club || 'The player\'s club') + ' is outside the followed leagues, so there are no season chances for the seller.</p>') +
      (longTerm ? '<p>' + esc(longTerm) + '</p>' : '') + (winText ? '<p class="fb-cap">' + esc(winText) + '</p>' : '') + '</div>') + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card(crest(B.tid, B.name) + ' ' + esc(B.name), 'Buying · ' + esc(compName(B.league)) + ' · rating shift ' + signed(deltaB, 3) + ' (log goal rate)',
        '<p class="fb-cap">Our season chances: grey bar now, blue bar after the move.</p>' + FB.chartBox('tr-odds-b', 220, 'Season chances before and after for the buyer') + oddsTableHTML(oB) + bd.units.map(depthHTML).join(''), { span: 6 }) +
      FB.card(S ? crest(S.tid, S.name) + ' ' + esc(S.name) : 'The seller', S ? 'Selling · ' + esc(compName(S.league)) + ' · rating shift ' + signed(deltaS, 3) : '',
        S ? '<p class="fb-cap">Our season chances: grey bar now, blue bar after the move.</p>' + FB.chartBox('tr-odds-s', 220, 'Season chances before and after for the seller') + oddsTableHTML(oS) + sd.units.map(depthHTML).join('') : FB.muted('No strengths-and-needs file for the seller: its season chances are not simulated here.'), { span: 6 })
    ) + '</div>' +
    (ff ? '<div class="fb-mt">' + FB.card('Fair fee and budget', 'The fee model, fitted on real fees, for this buyer.',
      '<div class="fb-prose"><p><b>Fair fee to ' + esc(B.name) + ': ' + money(ff[0]) + '</b> (middle half of similar deals ' + moneyRange(ff[1], ff[2]) + '), from the player\'s value over the next four seasons (' + num(P.v2, 1) + ' points above replacement), age, position, minutes and both clubs\' strength. Sofascore\'s market value, for reference: ' + money(P.mv) + '.</p>' +
      (has(bs.mid) ? '<p>' + esc(B.name) + '\'s budget for a summer window: about ' + money(bs.mid) + ' (25-75%: ' + moneyRange(bs.lo, bs.hi) + '); next window (' + esc(bn.window || '') + '): ' + moneyRange(bn.lo, bn.hi) + '. The fair fee is ' + affordWord(ff[0], bud) + ' its summer budget.</p>' : '<p class="fb-cap">No budget estimate for ' + esc(B.name) + ' yet.</p>') +
      '<p class="fb-cap">Fair value index ' + (has(P.fvi) ? P.fvi : '—') + ' (100 = the median regular of the top five leagues; not euros). ' + esc(HONEST) + ' Wages are unknown.</p></div>') + '</div>' : '') +
    '<div class="fb-mt">' + FB.card('Players out', 'Tick players leaving ' + esc(B.name) + ' in the same deal; their minutes go to the next in line.', '<div class="fb-va-outs" id="tr-outs">' + (outOpts || FB.muted('No squad on record.')) + '</div>') + '</div>';
  tb.innerHTML = h;
  var oddsChart = function (id, o) {
    var c = el.querySelector('#' + id);
    if (!c) return;
    var rows = o ? o.rows.filter(function (r) { return !r.pts; }) : [];
    if (!rows.length) { c.remove(); return; }
    QKC.bar(c, { horizontal: true, labelWidth: 120, fmt: function (v) { return pct(v, 1); }, valName: 'Our season chance', catName: 'Outcome',
      cats: rows.map(function (r) { return r.label; }), series: [{ name: 'Now', data: rows.map(function (r) { return r.base; }), color: QK.cssVar('--ink-4') }, { name: 'After', data: rows.map(function (r) { return r.after; }), color: 'model' }], label: 'Our season chances before and after the move' });
  };
  oddsChart('tr-odds-b', oB);
  oddsChart('tr-odds-s', oS);
  Array.prototype.forEach.call(el.querySelectorAll('#tr-outs [data-out]'), function (cb) {
    cb.addEventListener('change', function () {
      var sel = Array.prototype.filter.call(el.querySelectorAll('#tr-outs [data-out]'), function (x) { return x.checked; }).map(function (x) { return x.getAttribute('data-out'); });
      FB.setQuery({ out: sel.join(',') || null }, true);
    });
  });
}

// ══ budgets ═════════════════════════════════════════════════════════════

function budgetLedgerHTML(d) {
  var b = d.budget || null, L = d.ledger || null;
  if (!b && !L) return FB.muted('No budget or ledger for this club yet.');
  var h = '';
  if (b && b.summer) {
    h += FB.kpis([
      FB.kpi('Summer window budget', money(b.summer.mid), { sub: '25-75%: ' + moneyRange(b.summer.lo, b.summer.hi) }),
      FB.kpi('Next window', moneyRange((b.next || {}).lo, (b.next || {}).hi), { sub: esc((b.next || {}).window || '') }),
      FB.kpi('Squad value (Sofascore)', money(b.squad_mv), { sub: has(b.squad_mv_n) ? b.squad_mv_n + ' of ' + (b.squad_n || 0) + ' players valued' : 'not yet fetched' }),
      L && L.last12 ? FB.kpi('Net spend, 12 months', netText(L.last12.net), { sub: 'spent ' + money(L.last12.spend) + ' · sold ' + money(L.last12.income) }) : ''
    ].filter(Boolean)) +
      '<p class="fb-cap">The budget is a model of what this club spends in a window from its previous window\'s spending and sales, its league\'s and its own strength' + (b.squad_mv ? ' and its squad\'s market value' : '') + ', fitted across the followed clubs on the latest summer window (out of sample, about half the clubs land inside their 25-75% range). Not a club statement; wages are unknown.</p>';
  }
  if (L) {
    var l12 = L.last12 || {};
    if (has(l12.value_added)) h += '<p class="fb-cap">Last 12 months: fair value of the signings ' + money(l12.fair_in) + ' for ' + money(l12.spend) + ' in fees; of the sales ' + money(l12.fair_out) + ' for ' + money(l12.income) +
      ' — value added in the market ' + (l12.value_added >= 0 ? '+' : '−') + money(Math.abs(l12.value_added)) + '. On the pitch: signings worth ' + num(l12.gar_in, 1) + ' GAR a season, departures ' + num(l12.gar_out, 1) + '.</p>';
  }
  return h;
}
function ledgerTables(el, d, prefix) {
  var L = d.ledger;
  if (!L) return;
  var cols = function (side) {
    return [
      { key: 'date', label: 'Date', fmt: function (v) { return '<span class="fb-num">' + esc(v) + '</span>'; } },
      { key: 'name', label: 'Player', sticky: true, fmt: function (v, x) { return plink(x.pid, v) + ' ' + roleBadge(x.role); } },
      { key: 'club_name', label: side === 'in' ? 'From' : 'To', fmt: function (v, x) { return clink(x.club, v); } },
      { key: 'kind', label: 'Type', fmt: function (v) { return kindTag(v); } },
      { key: 'fee', label: 'Fee', num: true, fmt: function (v, x) { return x.kind === 'fee' ? money(v) : x.kind === 'free' ? 'Free' : '—'; } },
      { key: 'fair', label: 'Fair fee', num: true, fmt: function (v) { return money(v); } },
      { key: 'post_min', label: 'Min since', num: true, fmt: function (v) { return has(v) ? intl(v) + '\'' : '—'; } },
      { key: 'grade', label: 'Grade', tip: side === 'in' ? 'As the buyer' : 'As the seller', fmt: function (v) { return grade(v); } }
    ];
  };
  if ((L.in || []).length) FB.table(prefix + '-in', cols('in'), L.in.slice(0, 15), {}); else FB.set(prefix + '-in', FB.muted('None in our data.'));
  if ((L.out || []).length) FB.table(prefix + '-out', cols('out'), L.out.slice(0, 15), {}); else FB.set(prefix + '-out', FB.muted('None in our data.'));
  var ws = (L.windows || []).slice();
  var wc = el.querySelector('#' + prefix + '-win');
  if (wc && ws.length) {
    var o = ws.slice().sort(function (a, b) { return String(a.window).localeCompare(String(b.window)); });
    QKC.bar(wc, { legend: true, fmt: function (v) { return money(v); }, valName: 'Transfer fees', catName: 'Transfer window', cats: o.map(function (w) { return w.label + (w.complete ? '' : ' *'); }),
      series: [{ name: 'Spent', data: o.map(function (w) { return w.spend || 0; }) }, { name: 'Sold', data: o.map(function (w) { return w.income || 0; }) }], label: 'Spending and sales by window' });
  } else if (wc) { wc.style.height = 'auto'; wc.innerHTML = FB.muted('No windows on record.'); }
}
function ledgerShell(prefix) {
  return FB.grid(
    FB.card('Signings', 'Newest first, up to 15.', '<div id="' + prefix + '-in"></div>', { span: 6, flush: true }) +
    FB.card('Departures', 'Newest first, up to 15.', '<div id="' + prefix + '-out"></div>', { span: 6, flush: true }) +
    FB.card('By window', 'Published fees; * from players\' transfer histories, still filling in.', FB.chartBox(prefix + '-win', 260, 'Spending and sales by window'), { span: 12 }));
}

function drawBudgets(el, body, q) {
  body.innerHTML = FB.loading('lines', 5);
  return Promise.all([leagueClubs(), loadTransfers()]).then(function (d) {
    if (!FB.alive(el)) return;
    var LC = d[0], TR = d[1];
    var b = (META || {}).budgets || {};
    var lgs = followedLeagues();
    var lg = q.lg && lgs.indexOf(q.lg) >= 0 ? q.lg : (q.club && LC.byId[String(q.club)] ? LC.byId[String(q.club)].league : (lgs.indexOf('premier-league') >= 0 ? 'premier-league' : lgs[0]));
    var clubs = LC.list.filter(function (c) { return c.league === lg; });
    var club = q.club && LC.byId[String(q.club)] ? LC.byId[String(q.club)] : null;
    body.innerHTML = FB.kpis([
      FB.kpi('Clubs with a budget', intl(b.n_clubs), { sub: 'fitted on the ' + esc(b.target_window || '') + ' window' }),
      FB.kpi('Rank correlation', b.ok ? num(b.spearman_cv, 2) : '—', { signal: true, sub: 'out of sample, 5 folds by club' }),
      FB.kpi('R² (log spend)', b.ok ? num(b.r2_log_cv, 2) : '—', { sub: 'out of sample' }),
      FB.kpi('Inside 25-75%', b.ok ? pct(b.inside_25_75_cv) : '—', { sub: 'clubs out of sample (50% is calibrated)' }),
      FB.kpi('Winter v summer', b.ok ? pct(b.winter_ratio) : '—', { sub: 'a winter window\'s share of a summer\'s' })
    ]) +
      '<div class="fb-mt">' + FB.toolbar([
        FB.field('League', FB.select('bu-lg', lgs.map(function (s) { return [s, compName(s)]; }), lg, 'League')),
        FB.field('Club', FB.select('bu-club', [['', 'Pick a club…']].concat(clubs.map(function (c) { return [c.id, c.name]; })), club ? club.id : '', 'Club', 'fb-va-wide'))
      ]) + '</div>' +
      '<div class="fb-mt" id="bu-club-body"></div>' +
      '<div class="fb-mt">' + FB.grid(
        FB.card('Net spend by club, latest window', compName(lg) + ' · published fees in, less fees out.', FB.chartBox('bu-net', 360, 'Net spend by club'), { span: 7 }) +
        FB.card('The league\'s windows', 'Spending and sales.', FB.chartBox('bu-lgwin', 360, 'League spending by window'), { span: 5 })
      ) + '</div>' +
      '<p class="fb-cap">' + (b.ok ? 'Inputs: ' + esc((b.features || []).join(', ')) + '.' : esc(b.reason || 'Budgets not fitted this build.')) + ' ' + esc(HONEST) + '</p>';
    var sl = el.querySelector('#bu-lg'), sc = el.querySelector('#bu-club');
    if (sl) sl.addEventListener('change', function () { FB.setQuery({ lg: sl.value, club: null }, true); });
    if (sc) sc.addEventListener('change', function () { FB.setQuery({ lg: lg, club: sc.value || null }, true); });
    var W = TR ? ((TR.T.windows || {})[lg] || {}) : {};
    var keys = Object.keys(W).sort();
    var last = W[keys[keys.length - 1]] || {};
    var net = {};
    (last.spenders || []).concat(last.sellers || []).forEach(function (c) { net[c[0]] = (c[1] || 0) - (c[2] || 0); });
    var nk = Object.keys(net).sort(function (a, b2) { return net[b2] - net[a]; });
    var nb = el.querySelector('#bu-net');
    if (nk.length) QKC.bar(nb, { horizontal: true, diverging: true, labels: true, labelWidth: 120, fmt: function (v) { return netText(v); }, cats: nk.map(function (t) { return FB.clubName(t, '#' + t); }),
      valName: 'Net spend', series: [{ name: 'Net spend', data: nk.map(function (t) { return net[t]; }) }], hrefs: nk.map(function (t) { return '#/value/budgets?lg=' + lg + '&club=' + t; }), label: 'Net spend by club' });
    else { nb.style.height = 'auto'; nb.innerHTML = FB.muted('No published fees in the latest window.'); }
    var lb = el.querySelector('#bu-lgwin');
    if (keys.length) QKC.bar(lb, { legend: true, fmt: function (v) { return money(v); }, valName: 'Transfer fees', catName: 'Transfer window', cats: keys.map(function (k) { return W[k].label || k; }),
      series: [{ name: 'Spent', data: keys.map(function (k) { return W[k].spend || 0; }) }, { name: 'Sold', data: keys.map(function (k) { return W[k].income || 0; }) }] });
    else { lb.style.height = 'auto'; lb.innerHTML = FB.muted('No windows on record.'); }
    var cb = el.querySelector('#bu-club-body');
    if (!club) { cb.innerHTML = FB.empty('Pick a club', 'Its budget for the next windows, the last 12 months in the market, and every signing and sale.'); return; }
    cb.innerHTML = FB.loading('lines', 4);
    return clubFile(club.id).then(function (cd) {
      if (!FB.alive(el)) return;
      if (!cd) { cb.innerHTML = FB.empty('No file for ' + club.name + ' yet'); return; }
      cb.innerHTML = FB.card(crest(club.id, club.name) + ' ' + FB.clubLink(club.id, club.name, { nocrest: true }), esc(compName(cd.league)) + ' · as of ' + esc(cd.as_of || ''), budgetLedgerHTML(cd) +
        '<p class="fb-cap"><a href="' + esc(FB.href.club(club.id)) + '">Club page →</a> · <a href="#/value/simulator?to=' + esc(club.id) + '">Simulate a signing →</a> · <a href="#/value/transfers?q=' + encodeURIComponent(club.name) + '">Its transfers →</a></p>') +
        '<div class="fb-mt">' + ledgerShell('bu') + '</div>';
      ledgerTables(el, cd, 'bu');
    });
  });
}

// ══ method ══════════════════════════════════════════════════════════════

function drawMethod(el, body) {
  var m = META, mod = m.model || {}, v = (m.validation || {}).r2 || {};
  var f = m.fee || {}, fv = f.validation || {}, cv = fv.cv || {}, ts = fv.time_split || {};
  var w = (mod.weights || []).slice();
  body.innerHTML = FB.grid(
    FB.card('What each action is worth', 'Goals of expected goal difference per action (possession-adjusted where marked), fitted at every build.', FB.chartBox('me-w', Math.max(300, w.length * 24), 'Weights by action'), { span: 6 }) +
    FB.card('Does it predict?', 'Held-out R² on matches not yet seen (walk-forward).', FB.chartBox('me-r2', 300, 'Held-out R² by predictor') + '<p class="fb-cap">' + esc(validationLine(m)) + '</p>', { span: 6 })
  ) + '<div class="fb-mt">' + FB.grid(
    FB.card('Replacement level by role', 'Gross goals added per 90 of the 20th-percentile regular; the number of regulars (900+ minutes in 12 months).', '<div id="me-rep"></div>', { span: 6, flush: true }) +
    FB.card('The fee model, out of sample', f.fitted ? 'Fitted on ' + intl(f.n_with_value) + ' of ' + intl(f.n_fees) + ' published fees.' : esc(f.reason || 'Not fitted this build.'), '<div id="me-fee"></div>', { span: 6, flush: true })
  ) + '</div>' +
    '<div class="fb-mt">' + FB.card('How it is made', '', '<div class="fb-prose"><p>Every player\'s minutes are measured in <b>goals of expected goal difference</b>: sixteen actions from each match (non-penalty xG, xA, key passes, carries, dribbles, passes in the opposition half, possession lost, tackles, interceptions, blocks, clearances, recoveries, aerials, errors, and for keepers goals prevented and claims) plus the match rating, weighted by how well they predicted later matches. GAR/90 is the value per 90 minutes above a replacement-level player in the same role; PAR turns it into league points. Competitions are put on one scale with the pooled model\'s league strengths.</p>' +
      '<p>Fitted on ' + intl(mod.fit_matches) + ' club matches: a ridge regression with signs fixed (more of a good action never lowers value) predicts each match\'s non-penalty xG difference from the line-ups\' earlier per-90 rates; the rating weight is a second stage on the same matches. Possession-adjusted actions are scaled by 50 / the opponent\'s possession. Validation: the last 60% of ' + intl((m.validation || {}).n_matches) + ' matches in five blocks from ' + esc((m.validation || {}).first_test_day || '') + ', each predicted by models fitted only on earlier matches. Football is noisy: a single match\'s goal difference is mostly luck.</p>' +
      '<p>The fair fee is a ridge regression of log published fees on the player\'s four-season value, projection, age, position, minutes and both clubs\' strength; budgets model a club\'s window spend from its previous window, its league, its strength and its squad\'s market value. ' + esc(HONEST) + ' <a href="#/model/methodology/value">Full methodology →</a></p></div>') + '</div>';
  var ws = w.slice().sort(function (a, b) { return (b.weight || 0) - (a.weight || 0); });
  if (ws.length) QKC.bar(el.querySelector('#me-w'), { horizontal: true, diverging: true, labels: true, labelWidth: 170, catName: 'Action', fmt: function (x) { return signed(x, 3); },
    cats: ws.map(function (x) { return x.label + (x.padj ? ' (p-adj)' : ''); }), valName: 'Goals per action', series: [{ name: 'Goals per action', data: ws.map(function (x) { return x.weight || 0; }) }], label: 'Weights by action' });
  if (v.xgd) {
    var lbl = { rating: 'Sofascore rating', team: 'Team\'s own form', box: 'Box score alone', value: 'Player value' };
    var ks = ['rating', 'team', 'box', 'value'];
    QKC.bar(el.querySelector('#me-r2'), { horizontal: true, legend: true, labelWidth: 120, fmt: function (x) { return pct(x, 1); }, valName: 'Held-out R²', cats: ks.map(function (k) { return lbl[k]; }),
      series: [{ name: 'xG difference', data: ks.map(function (k) { return v.xgd[k]; }) }, { name: 'Goal difference', data: ks.map(function (k) { return (v.gd || {})[k]; }) }] });
  } else FB.set('me-r2', FB.muted('No validation this build.'));
  var rep = m.replacement || {};
  FB.table('me-rep', [
    { key: 'r', label: 'Role', fmt: function (x) { return roleBadge(x) + ' ' + esc(roleLabel(x)); } },
    { key: 'rep', label: 'Replacement', num: true, fmt: function (x) { return g2(x); } },
    { key: 'n', label: 'Regulars', num: true }
  ], MAIN_ROLES.map(function (r) { return { r: r, rep: rep[r], n: (m.regulars || {})[r] || 0 }; }), {});
  if (f.fitted) {
    var row = function (l, x, bold) { return { l: l, bold: bold, ef: x.error_factor, w50: x.within_50pct, r2: x.r2_log, sp: x.spearman, mae: x.median_abs_eur }; };
    var rows = [row('Fee model, 5 folds by player', cv.model || {}, true), row('Value and age only', cv.value_age_only || {}), row('Median by tier and position', cv.baseline_median || {})];
    if (ts.model) rows.push(row('Fee model, later fees (from ' + ts.test_from + ')', ts.model, true), row('Baseline, later fees', ts.baseline_median || {}));
    FB.table('me-fee', [
      { key: 'l', label: 'Out of sample', fmt: function (x, r) { return r.bold ? '<b>' + esc(x) + '</b>' : esc(x); } },
      { key: 'ef', label: 'Typical error', num: true, tip: 'exp(median absolute error of log fee)', fmt: function (x) { return has(x) ? '×' + num(x, 2) : '—'; } },
      { key: 'w50', label: 'Within ±50%', num: true, fmt: function (x) { return pct(x); } },
      { key: 'r2', label: 'R² (log)', num: true, fmt: function (x) { return num(x, 2); } },
      { key: 'sp', label: 'Rank corr.', num: true, fmt: function (x) { return num(x, 2); } },
      { key: 'mae', label: 'Median miss', num: true, fmt: function (x) { return money(x); } }
    ], rows, {});
  } else FB.set('me-fee', FB.muted(f.reason || 'No fee model this build.'));
}

// ══ who moves next (value/moves.json and the clubs' `movement`: UNIFIED_PAYLOADS 15, docs/_design/MOVES_VIEWS.md) ══

/* moves.json is about 0.9 MB, so it is read only once a club file says the club has a movement block (a missing
   file would be a failed request); it is cached for the session. */
var MOVES = null, MOVES_P = null;
var TYPE_SLOT = { transfer: 1, free: 3, loan: 5, loan_end: 4, release: 8 };
var DEST_SLOT = { same: 1, stronger: 3, weaker: 2, outside: 8 };
var UNIT_WEAK = { GK: 'G', CB: 'D', FB: 'D', MID: 'M', ATT: 'F', ST: 'F' };
var BASE_TAG = '<span class="qk-tag fb-mv-base" data-tip="A base rate, not a player-level forecast: how often similar players left in the last window of the same kind. Our player-level model is being forward-tested this window; it did not beat this base rate on last summer\'s window." tabindex="0">base rate</span>';
function mvPct(p) { if (!has(p)) return '—'; if (p > 0 && p < 0.005) return '<1%'; return Math.round(p * 100) + '%'; }
function mvPct1(p) { if (!has(p)) return '—'; if (p > 0 && p < 0.0005) return '<0.1%'; return p < 0.1 ? (p * 100).toFixed(1) + '%' : Math.round(p * 100) + '%'; }
function slotVar(n) { return 'var(--c-' + (n || 8) + ')'; }
function movesLoad() {
  if (MOVES) return Promise.resolve(MOVES);
  if (MOVES_P) return MOVES_P;
  MOVES_P = FB.load('value/moves.json').then(function (d) {
    if (!d || !d.fields || !(d.meta || {}).ok) return null;
    var I = {};
    d.fields.forEach(function (f, i) { I[f] = i; });
    var byId = {};
    (d.rows || []).forEach(function (r) {
      byId[String(r[I.id])] = { id: String(r[I.id]), tid: r[I.tid], p: r[I.p], basis: r[I.basis], band: r[I.band], loan: r[I.loan], share: r[I.share], types: r[I.types] || [], dests: r[I.dests] || [], p_club: r[I.p_club] };
    });
    MOVES = { meta: d.meta, byId: byId };
    return MOVES;
  });
  return MOVES_P;
}
function typeLabel(meta, k) { return ((meta || {}).type_labels || {})[k] || k; }
function destLabel(meta, k) { return ((meta || {}).dest_labels || {})[k] || k; }
function bandWord(b) { return b === 'regular' ? 'regular' : b === 'rotation' ? 'rotation' : b === 'fringe' ? 'fringe' : ''; }
/* A 0-100% bar split by the five ways of leaving in the meta's fixed order (p x types[k]), with the whole percentage. */
function moveBar(row, meta, big) {
  var types = (meta || {}).types || [];
  var segs = types.map(function (k, i) {
    var w = 100 * (row.p || 0) * ((row.types || [])[i] || 0);
    return w > 0.05 ? '<i style="width:' + w.toFixed(2) + '%;background:' + slotVar(TYPE_SLOT[k]) + '" title="' + esc(typeLabel(meta, k)) + ' ' + mvPct((row.p || 0) * ((row.types || [])[i] || 0)) + '"></i>' : '';
  }).join('');
  return '<span class="fb-mv-track' + (big ? ' lg' : '') + '" role="img" aria-label="Chance of moving ' + esc(mvPct(row.p)) + '">' + segs + '</span>';
}
/* One mix (types or dests, summing to 1) as a stacked bar with its labels. */
function mixBar(vals, keys, label, slot) {
  var parts = keys.map(function (k, i) { return { k: k, v: vals[i] || 0 }; });
  return '<div class="fb-mv-mix"><span class="fb-mv-track lg" role="img" aria-label="' + esc(parts.map(function (x) { return label(x.k) + ' ' + mvPct(x.v); }).join(', ')) + '">' +
    parts.map(function (x) { return x.v > 0.001 ? '<i style="width:' + (100 * x.v).toFixed(2) + '%;background:' + slotVar(slot[x.k]) + '"></i>' : ''; }).join('') + '</span>' +
    '<div class="fb-mv-mixlab">' + parts.filter(function (x) { return x.v >= 0.005; }).map(function (x) { return '<span><i style="background:' + slotVar(slot[x.k]) + '"></i>' + esc(label(x.k)) + ' <b>' + mvPct(x.v) + '</b></span>'; }).join('') + '</div></div>';
}

FB.moves = {
  load: movesLoad,
  pct: mvPct,
  /* The squad table's cell: the bar, the percentage, an "on loan" chip and the role band; a dash without an estimate. */
  cell: function (row, meta) {
    if (!row || !has(row.p)) return '<span class="qk-muted" data-tip="Not enough recent minutes for an estimate">–</span>';
    return '<span class="fb-mv-cell">' + moveBar(row, meta) + '<b class="fb-num">' + mvPct(row.p) + '</b>' + (row.loan ? '<span class="qk-tag fb-mv-loan">on loan</span>' : '') +
      (bandWord(row.band) ? '<span class="fb-mv-band">' + esc(bandWord(row.band)) + '</span>' : '') + '</span>';
  },
  /* The key above the squad tables: what the bar's colours mean, and that the chance is a base rate. */
  keyHTML: function (meta, mv) {
    var types = (meta || {}).types || [];
    return '<div class="fb-mv-key"><span class="fb-mv-key-t">Chance of moving, ' + esc((mv || {}).horizon || (meta || {}).horizon || 'the coming window') + '</span>' + BASE_TAG +
      QK.keys(types.map(function (k) { return { name: typeLabel(meta, k), color: slotVar(TYPE_SLOT[k]), kind: 'dot' }; })) + '</div>';
  },
  /* The club's outlook and targets (club page, Moves & needs), from value/club/<tid>.json `movement`. */
  clubViews: function (el, d) {
    var mv = d && d.movement;
    if (!el || !mv) { if (el) el.innerHTML = ''; return; }
    var units = ['G', 'D', 'M', 'F'];
    var uname = { G: 'Goalkeeper', D: 'Defence', M: 'Midfield', F: 'Attack' };
    var need = {};
    (d.weaknesses || []).forEach(function (k) { if (UNIT_WEAK[k]) need[UNIT_WEAK[k]] = 1; });
    var gap = null, gv = -1e9;
    units.forEach(function (u) { var g = ((mv.expected_out || {})[u] || 0) - ((mv.expected_in || {})[u] || 0); if (g > gv) { gv = g; gap = u; } });
    var basis = mv.basis || {};
    var tipOut = 'A base rate: the sum of each player\'s chance of leaving, from how often similar players (same league, same share of the minutes) left in ' + (basis.window || 'the last window of the same kind') + '.';
    var tipIn = 'A base rate: the ' + (basis.arrivals === 'region' ? 'region\'s' : 'league\'s') + ' clubs\' arrivals per club in ' + (basis.window || 'the last window of the same kind') + ', split by position as they were.';
    var rows = units.map(function (u) {
      var tags = (need[u] ? '<span class="qk-tag fb-mv-need" data-tip="A weak unit on the value grades below" tabindex="0">need</span>' : '') + (u === gap && gv > 0.05 ? '<span class="qk-tag signal" data-tip="More players expected to leave than to arrive here than at any other position" tabindex="0">most to replace</span>' : '');
      var pa = (mv.p_add || {})[u];
      return '<tr><td><b>' + esc(uname[u]) + '</b> ' + tags + '</td><td class="num">' + num((mv.expected_out || {})[u], 1) + '</td><td class="num">' + num((mv.expected_in || {})[u], 1) + '</td>' +
        '<td class="num"><span class="fb-mv-cell"><span class="fb-mv-track"><i style="width:' + (100 * (pa || 0)).toFixed(1) + '%;background:var(--signal)"></i></span><b class="fb-num">' + mvPct(pa) + '</b></span></td></tr>';
    }).join('');
    var outlook = FB.kpis([
      FB.kpi('Expected departures', num(mv.out_total, 1), { sub: BASE_TAG + ' players', tip: tipOut }),
      FB.kpi('Expected arrivals', num(mv.in_total, 1), { sub: BASE_TAG + ' players', tip: tipIn })
    ], 'fb-mv-kpis') +
      '<div class="qk-table-wrap fb-mt"><table class="qk-table dense"><thead><tr><th>Unit</th><th class="num">Expected out</th><th class="num">Expected in</th><th class="num" data-tip="The chance of adding at least one player there">Chance of adding</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    var ts = [];     // no potential signings on the club page (user, 25 Oct 2026); the payload keeps mv.targets
    el.innerHTML = FB.secHead('Who moves next: ' + esc(mv.horizon || ''), 'Our outlook for the window: who is likely to leave and what the club usually brings in, by unit. Departures and arrivals are base rates from the last window of the same kind.', '', 'Movement') +
      FB.grid(
        FB.card('Outlook: ' + esc(mv.horizon || ''), 'Expected departures and arrivals by unit, with the chance of adding at least one player there.', outlook, { span: 5 }) +
        FB.card('Out and in by unit', 'Players expected to leave (left) and to arrive (right) this window.', FB.chartBox('mv-bf', 230, 'Expected departures and arrivals by unit'), { span: 7 })
      ) +
      (ts.length ? '<div class="fb-mt">' + FB.card('Who they could sign', 'Ranked by chance of joining: availability × fit × plausibility. A shortlist, not a prediction of the signing.', '<div id="mv-targets"></div>', { flush: true,
        right: '<span class="qk-tag" data-tip="' + esc(targetsTip()) + '" tabindex="0">How good is the list?</span>' }) + '</div>' : '');
    QKC.butterfly(el.querySelector('#mv-bf'), { cats: units.map(function (u) { return uname[u]; }), labels: true, fmt: function (v) { return num(v, 1); }, valName: 'Players (expected)',
      left: { name: 'Expected out', data: units.map(function (u) { return (mv.expected_out || {})[u] || 0; }), color: QK.cssVar('--c-2') },
      right: { name: 'Expected in', data: units.map(function (u) { return (mv.expected_in || {})[u] || 0; }), color: QK.cssVar('--c-1') }, label: 'Expected departures and arrivals by unit' });
    if (!ts.length) return;
    QK.leaderboard(el.querySelector('#mv-targets'), { dense: true, rank: true, sort: { key: 'p_join', dir: 'desc' }, caption: 'Who they could sign', columns: [
      { key: 'name', label: 'Player', type: 'entity', sub: 'sub', href: function (t) { return FB.href.player(t.id); } },
      { key: 'club', label: 'Club', fmt: function (v, t) { return (t.tid ? clink(t.tid, v) : esc(v || '—')) + (t.league ? ' <span class="qk-muted">' + esc(compName(t.league)) + '</span>' : ''); } },
      { key: 'p_join', label: 'Chance of joining', num: true, tip: 'The chance the player joins this club in the window; 1-3% is a strong target', fmt: function (v) { return '<b class="fb-mv-join">' + mvPct1(v) + '</b>'; } },
      { key: 'p_move', label: 'Availability', num: true, tip: 'The player\'s chance of leaving the current club this window (a base rate)', fmt: function (v) { return '<span class="fb-mv-cell"><span class="fb-mv-track"><i style="width:' + (100 * (v || 0)).toFixed(1) + '%;background:var(--ink-3)"></i></span><b class="fb-num">' + mvPct(v) + '</b></span>'; } },
      { key: 'q_gap', label: 'Fit', num: true, tip: 'The player\'s rating against the club\'s in that unit, and how much of a starter there is expected to leave', fmt: function (v, t) { return '<span class="fb-mv-fit"><b class="fb-num">' + signed(v, 2) + '</b><small>v your ' + esc((uname[t.unit] || 'unit').toLowerCase()) + (has(t.need) ? ' · ×' + num(t.need, 1) + ' of a starter leaving' : '') + '</small></span>'; } },
      { key: 'plaus', label: 'Plausibility', num: true, tip: 'This club\'s share of the player\'s likely destinations, against an average club of our leagues (1×)', fmt: function (v) { return has(v) ? num(v, 1) + '×' : '—'; } },
      { key: 'fee', label: 'Fair fee', num: true, tip: 'Our fee model for this buyer; the budget fit as on the targets below', fmt: function (v, t) { return (has(v) ? money(v) : '—') + (t.afford ? ' <span class="fb-va-aff a-' + esc(t.afford) + '">' + (t.afford === 'yes' ? 'fits' : t.afford === 'stretch' ? 'stretch' : 'beyond') + '</span>' : ''); } },
      { key: 'why', label: 'Why', sort: false, fmt: function (v) { return '<span class="fb-mv-why">' + esc(v || '') + '</span>'; } }
    ], rows: ts.map(function (t) { return FB.merge(t, { sub: [has(t.age) ? t.age : '', t.role || uname[t.unit] || ''].filter(function (x) { return x !== ''; }).join(' · ') }); }) });
  }
};
function targetsTip() {
  var v = (((MOVES || {}).meta || {}).validation || {}).targets;
  if (v && has(v.precision10)) return 'Tested on last summer\'s window: ' + (100 * v.precision10).toFixed(2) + '% of the clubs\' top-ten names were signed by that club, against ' + (100 * (v.precision10_avail || 0)).toFixed(2) + '% for the most available players alone and ' + (100 * (v.precision10_same_league || 0)).toFixed(2) + '% for same-league players first. Read it as a shortlist.';
  return 'Tested on last summer\'s window before publishing: the ranked lists found the players clubs signed several times more often than availability alone. Read it as a shortlist, not a prediction. Numbers on the Model page.';
}

/* FB.movementCard(el, pid, {tid (his club now), until (contract end, Sofascore)}): the player's "Movement" card, or
   nothing (el emptied, resolves false) when his club has no movement block or the payload has no row for him. */
FB.movementCard = function (el, pid, opts) {
  var o = opts || {};
  if (!el) return Promise.resolve(false);
  var none = function () { if (FB.alive(el)) el.innerHTML = ''; return false; };
  var tid = o.tid;
  /* value/meta.json (27 KB) names the followed leagues; players.json is not needed here */
  return (META ? Promise.resolve(META) : FB.load('value/meta.json').then(function (m) { if (!META) META = m; return META; }))
    .then(function () { return leagueClubs(); }).then(function () { return tid ? clubFile(tid) : null; }).then(function (cd) {
    if (!cd || !cd.movement) return none();
    return movesLoad().then(function (M) {
      if (!M || !FB.alive(el)) return none();
      var r = M.byId[String(pid)] || M.byId[FB.personId(pid)];
      if (!r || !has(r.p)) return none();
      var meta = M.meta || {}, hz = cd.movement.horizon || meta.horizon || 'the coming window';
      var league = compName(cd.league), band = bandWord(r.band);
      var basis = r.basis === 'loan' ? 'players on loan in the same region' : r.basis === 'region' ? 'players in the same region' : 'similar players in ' + league + (band ? ', ' + band : '');
      var vt = (meta.validation || {}).type || {}, vd = (meta.validation || {}).dest || {};
      var mtip = 'Models that passed their held-out test on last summer\'s window' + (has(vt.accuracy_movers) ? ' (how: ' + Math.round(100 * vt.accuracy_movers) + '% of movers\' ways called right)' : '') + '.';
      var facts = [];
      if (o.until) facts.push('Contract ends ' + esc(FB.fmtDate(o.until, { weekday: false, year: true }).replace(/^\d+ /, '')) + ' (Sofascore)');
      if (r.loan) facts.push('On loan at ' + esc(cd.name || 'the club'));
      if (has(r.share)) facts.push(Math.round(100 * r.share) + '% of ' + esc(cd.name || 'the club') + '\'s minutes since joining');
      el.innerHTML = FB.card('Movement: ' + esc(hz), 'Our chance the player leaves ' + esc(cd.name || 'the current club') + ' this window, and the type and destination of any move.',
        FB.kpis([FB.kpi('Chance of moving', mvPct(r.p), { signal: true, sub: BASE_TAG + ' ' + esc(basis), tip: 'How often ' + basis + ' left in the last window of the same kind. A base rate, not a player-level forecast.' }),
          FB.kpi('Joins a club we follow', mvPct(r.p_club), { sub: 'one of our leagues\' clubs, this window', tip: 'The chance of leaving times the chance the move is a transfer, a free or a loan to a club of the leagues we follow' })], 'fb-mv-kpis') +
        '<div class="fb-mv-if"><div class="qk-kicker" data-tip="' + esc(mtip) + '" tabindex="0">Type of move</div>' + mixBar(r.types || [], meta.types || [], function (k) { return typeLabel(meta, k); }, TYPE_SLOT) +
        '<div class="qk-kicker fb-mt" data-tip="' + esc(mtip + (has(vd.n) ? ' Destination tested on ' + intl(vd.n) + ' moves.' : '')) + '" tabindex="0">Destination</div>' + mixBar(r.dests || [], meta.dests || [], function (k) { return destLabel(meta, k); }, DEST_SLOT) + '</div>' +
        (facts.length ? '<p class="fb-cap">' + facts.join(' · ') + '</p>' : ''), { cls: 'fb-mv-card' });
      return true;
    });
  });
};

// ══ the club page's strengths and needs (exported for clubs.js) ═══════════

/* FB.valueNeeds(el, tid): the strengths-and-needs card with targets, budget and ledger, or nothing when the club has no file. */
FB.valueNeeds = function (el, tid) {
  if (!el) return Promise.resolve(null);
  return Promise.all([loadCore(), leagueClubs()]).then(function () {
    return clubFile(tid);
  }).then(function (d) {
    if (!FB.alive(el)) return null;
    if (!d || !d.units) { el.innerHTML = ''; return null; }
    var units = {};
    d.units.forEach(function (u) { units[u.unit] = u; });
    var pfx = 'vn' + tid;
    var evidence = function (u) {
      if (!u) return '';
      var e = u.evidence || {};
      return '<b>' + esc(u.label) + '</b>: ' + g2(u.rate) + ' GAR/90, ' + FB.ordinal(u.rank) + ' of ' + u.n + ' in ' + esc(compName(d.league)) +
        (e.component && has(e.delta) && Math.abs(e.delta) >= 0.005 ? ' — ' + esc(e.component) + ' ' + signed(e.delta, 2) + ' a player per 90 against the league' : '') +
        (u.few ? ' (few minutes: graded on the squad\'s best there)' : '') + (u.empty ? ' (no current player has played here)' : '') + '.';
    };
    var win = d.window;
    el.innerHTML = FB.card('Strengths and needs', esc(compName(d.league)) + ' · graded against the league\'s clubs on the projected value of the players used this season · as of ' + esc(d.as_of || ''),
      FB.chartBox(pfx + '-units', 260, 'Unit percentiles in the league') + '<div id="' + pfx + '-tbl"></div>' +
      '<div class="qk-grid fb-mt"><div class="qk-span-6"><div class="fb-va-sw up">Top strengths</div><ol class="fb-va-ol">' + (d.strengths || []).map(function (k) { return '<li>' + evidence(units[k]) + '</li>'; }).join('') + '</ol></div>' +
      '<div class="qk-span-6"><div class="fb-va-sw down">Top weaknesses</div><ol class="fb-va-ol">' + (d.weaknesses || []).map(function (k) { return '<li>' + evidence(units[k]) + '</li>'; }).join('') + '</ol></div></div>' +
      '<div class="fb-va-sw fb-mt">Ways to improve</div><p class="fb-cap">For each weakness, the players who would add the most projected value over the weakest current regular there, among realistic targets: a club of similar or lower strength, a league at most a step stronger, aged 31 or under, 900+ minutes in the last 12 months. Points assume 85% of the minutes. ' +
      (win ? (win.open ? 'The window is open (usually until ' + esc(win.until) + ').' : 'The window is closed; the next usually opens ' + esc(win.next || '') + '.') : '') + '</p>' +
      (d.weaknesses || []).map(function (k) { return '<div class="fb-va-unit">' + esc((units[k] || {}).label || k) + '</div><div id="' + pfx + '-t-' + k + '"></div>'; }).join('') +
      '<div class="fb-va-sw fb-mt">Transfer budget and ledger</div>' + budgetLedgerHTML(d) + '<div class="fb-mt">' + ledgerShell(pfx) + '</div>' +
      '<p class="fb-cap">' + esc(HONEST) + ' <a href="#/value?club=' + esc(d.tid) + '">The squad on the value table →</a> · <a href="#/value/simulator?to=' + esc(d.tid) + '">Transfer simulator →</a></p>');
    QKC.bar(el.querySelector('#' + pfx + '-units'), { horizontal: true, labels: true, labelWidth: 150, max: 100, fmt: function (x) { return num(x, 0); },
      cats: d.units.map(function (u) { return u.label + ' (' + (u.grade || '—') + ')'; }), valName: 'Percentile in the league', series: [{ name: 'Percentile in the league', data: d.units.map(function (u) { return u.pct; }) }],
      colors: d.units.map(function (u) { return u.pct >= 60 ? QK.cssVar('--st-good') : u.pct >= 40 ? QK.cssVar('--st-warn') : QK.cssVar('--st-crit'); }) });
    FB.table(pfx + '-tbl', [
      { key: 'label', label: 'Unit', sticky: true },
      { key: 'pct', label: 'Grade', fmt: function (x, u) { return grade(u.grade); } },
      { key: 'rate', label: 'GAR/90', num: true, pctl: 'pct', fmt: function (x) { return g2(x); } },
      { key: 'rank', label: 'Rank', num: true, fmt: function (x, u) { return x + '/' + u.n; } },
      { key: 'depth', label: 'Players (minutes)', sort: false, fmt: function (x) { return (x || []).filter(function (p) { return p.min > 0; }).slice(0, 3).map(function (p) { return plink(p.id, p.name) + ' <span class="qk-muted fb-num">' + p.min + '\'</span>'; }).join(', ') || '—'; } }
    ], d.units, {});
    (d.weaknesses || []).forEach(function (k) {
      var ts = (d.targets || {})[k] || [];
      if (!ts.length) { FB.set(pfx + '-t-' + k, FB.muted('No realistic target clears the filters for this unit.')); return; }
      FB.table(pfx + '-t-' + k, [
        { key: 'name', label: 'Player', sticky: true, fmt: function (x, t) { return plink(t.id, x) + ' ' + roleBadge(t.role); } },
        { key: 'age', label: 'Age', num: true },
        { key: 'club', label: 'Club', fmt: function (x, t) { return t.free ? FB.badge('no club') : clink(t.tid, x); } },
        { key: 'min', label: 'Min (12m)', num: true },
        { key: 'gain90', label: 'Gain/90', num: true, tip: 'Over the weakest current regular in the unit', fmt: function (x) { return '<b>' + g2(x) + '</b>'; } },
        { key: 'gain_pts_rest', label: 'Pts, rest', num: true, fmt: function (x) { return has(x) ? signed(x, 1) : '—'; } },
        { key: 'fee', label: 'Fair fee', num: true, fmt: function (x, t) { return has(x) ? '<span data-tip="' + esc(moneyRange(t.fee_lo, t.fee_hi)) + '">' + money(x) + '</span>' : '—'; } },
        { key: 'afford', label: 'Budget', fmt: function (x) { return x ? '<span class="fb-va-aff a-' + esc(x) + '">' + (x === 'yes' ? 'fits' : x === 'stretch' ? 'stretch' : 'beyond') + '</span>' : '—'; } },
        { key: 'mv', label: 'Sofascore value', num: true, fmt: function (x) { return money(x); } },
        { key: 'sim', label: '', sort: false, fmt: function (x, t) { return '<a class="fb-link" href="#/value/simulator?p=' + esc(t.id) + '&to=' + esc(d.tid) + '">Simulate →</a>'; } }
      ], ts, {});
    });
    ledgerTables(el, d, pfx);
    return d;
  });
};

})(window.FB);
