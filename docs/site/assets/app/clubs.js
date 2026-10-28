/* The Quant Footballer — Clubs: the directory and ONE page per club (or national team) across every competition.
 *
 *   #/clubs                    every club on the pooled cross-league scale, a jump-to-any-club search
 *   #/clubs/leagues            the leagues on one scale and the bridges between continents
 *   #/clubs/nations            national teams on the international model, next internationals, a pricer
 *   #/clubs/pricer[?a=&b=&v=]  "If they met": our chances for any two clubs from the pooled Dixon-Coles model, in the browser
 *   #/club/<tid>[?tab=overview|seasons|squad|matches|transfers&c=<slug>&e=<era>]
 *       overview   record in the filter, year by year (all competitions summed per season), this season by
 *                  competition, next and last matches, ratings, strengths and needs, the competition dossier (?c=)
 *       seasons    every season, every competition: finish, record, coverage, link to that edition
 *       squad      the current squad by position: shirt, age, nationality, value, contract, this season's line
 *       matches    fixtures and results across every competition, xG by match, points per game by season
 *       transfers  who moves next (the outlook, when the moves payload has it), strengths and needs, the transfer
 *                  budget and the ledger (followed leagues). No potential signings on the club page (user, 25 Oct
 *                  2026: "remove potential signings from team pages"); the overview has the top performers instead
 * The movement views (docs/_design/MOVES_VIEWS.md) come from FB.moves in value.js; they draw nothing when the
 * payload has no `movement` for the club.
 *
 * Reads pool.json, nations.json, hub.json, clubs_index.json, clubs/<tid>.json (UNIFIED_PAYLOADS §3, §9-13),
 * value/club/<tid>.json (§11-12: requested only for clubs in a followed league this season) and, for the
 * dossier, the competition's probs/table/strength/team_stats/players_live/teams. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, pct = FB.pct, signed = FB.signed;

var VALUE_LEAGUES = ['premier-league', 'la-liga', 'serie-a', 'bundesliga', 'ligue-1', 'eredivisie', 'primeira-liga', 'brasileirao', 'mls', 'saudi-pro-league', 'liga-mx', 'belgian-pro-league', 'liga-argentina'];
var POS_ORDER = ['G', 'D', 'M', 'F'];
var POS_SLOT = { G: 4, D: 1, M: 3, F: 8 };
var DEAL_KIND = { fee: 'Transfer', free: 'Free', undisclosed: 'Undisclosed fee', loan: 'Loan', loan_end: 'Loan return', youth: 'Promoted' };

function has(v) { return v !== undefined && v !== null && !(typeof v === 'number' && isNaN(v)); }
function enc(s) { return encodeURIComponent(s); }
function moneyRange(lo, hi) { return has(lo) && has(hi) ? FB.money(lo) + '–' + FB.money(hi) : '—'; }
function grade(g) { return g ? '<span class="fb-cl-grade g-' + esc(g) + '">' + esc(g) + '</span>' : '<span class="qk-muted">—</span>'; }
function resCls(gf, ga) { return !isNum(gf) || !isNum(ga) ? '' : gf > ga ? 'W' : gf === ga ? 'D' : 'L'; }
function posSlotHex(p) { return QK.cssVar('--c-' + (POS_SLOT[p] || 7)); }
function ppgOf(r) { return r.played ? (3 * r.w + r.d) / r.played : null; }
/* A club's mark for the kit's entity cells: the crest where there is one, else the monogram. */
function clubMark(tid, name) { return { logo: tid ? FB.crestUrl(tid) : null, name: name || FB.clubName(tid) || '?' }; }
/* A v2 leaderboard (kit QK.leaderboard: entity, bar and percentile cells) with FB.table's options. */
function board(el, cols, list, o) {
  if (!el) return null;
  o = o || {};
  return QK.leaderboard(el, { columns: cols, rows: list, sort: o.sort || null, rank: !!o.rank, dense: o.dense !== false, maxHeight: o.maxHeight, caption: o.caption, rowClass: o.rowClass });
}

// ── Dixon-Coles in the browser (the pooled and international fits publish attack, defence, rho, home advantage) ──

function poissonPmf(k, lam) { var p = Math.exp(-lam); for (var i = 1; i <= k; i++) p *= lam / i; return p; }
function dcMatrix(home, away, model, homeAdv) {
  var lamH = Math.exp(home.attack + away.defence + (homeAdv || 0));
  var lamA = Math.exp(away.attack + home.defence);
  var k = (model.max_goals || 8) + 1, rho = model.rho || 0;
  var m = [], total = 0, i, j;
  for (i = 0; i < k; i++) {
    m.push([]);
    for (j = 0; j < k; j++) {
      var p = poissonPmf(i, lamH) * poissonPmf(j, lamA);
      if (i === 0 && j === 0) p *= 1 - lamH * lamA * rho;
      else if (i === 1 && j === 0) p *= 1 + lamA * rho;
      else if (i === 0 && j === 1) p *= 1 + lamH * rho;
      else if (i === 1 && j === 1) p *= 1 - rho;
      p = Math.max(p, 0);
      m[i].push(p); total += p;
    }
  }
  var h = 0, d = 0, a = 0, o25 = 0, btts = 0, best = [0, 0, -1];
  for (i = 0; i < k; i++) for (j = 0; j < k; j++) {
    var q = m[i][j] / total;
    m[i][j] = q;
    if (i > j) h += q; else if (i === j) d += q; else a += q;
    if (i + j >= 3) o25 += q;
    if (i >= 1 && j >= 1) btts += q;
    if (q > best[2]) best = [i, j, q];
  }
  return { h: h, d: d, a: a, lamH: lamH, lamA: lamA, o25: o25, btts: btts, score: best[0] + '–' + best[1], pScore: best[2], m: m };
}
/* If they met: our home / draw / away chance (the bar, home on the left as on the game cards), the tiles and the
   score grid. */
function chanceHTML(id, home, away, model, neutral) {
  var r = dcMatrix(home, away, model, neutral ? 0 : model.home_adv);
  return '<div class="fb-cl-price">' + FB.wpBar({ h: r.h, d: r.d, a: r.a }, home.team, away.team) +
    FB.kpis([
      FB.kpi(home.team + ' win', pct(r.h), { signal: r.h >= r.a, sub: neutral ? 'our chance, neutral venue' : 'our chance, at home' }),
      FB.kpi('Draw', pct(r.d), { sub: 'our chance' }),
      FB.kpi(away.team + ' win', pct(r.a), { signal: r.a > r.h, sub: neutral ? 'our chance, neutral venue' : 'our chance, away' }),
      FB.kpi('Expected goals', num(r.lamH, 2) + '–' + num(r.lamA, 2), { sub: 'most likely ' + r.score + ' (' + pct(r.pScore, 1) + ')' }),
      FB.kpi('3 or more goals', pct(r.o25), { sub: '2 or fewer ' + pct(1 - r.o25) }),
      FB.kpi('Both score', pct(r.btts), { sub: 'one or neither ' + pct(1 - r.btts) })
    ], 'fb-mt') +
    '<div class="qk-card-sub fb-mt">Chance of each score (' + esc(home.team) + ' down the side, ' + esc(away.team) + ' across)</div>' +
    FB.chartBox(id, 300, 'Chance of each score') + '</div>';
}
function drawScoreGrid(el, id, home, away, model, neutral) {
  var r = dcMatrix(home, away, model, neutral ? 0 : model.home_adv);
  var n = 6, data = [];
  for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) data.push([j, i, Math.round(r.m[i][j] * 1000) / 10]);
  var box = el.querySelector('#' + id);
  if (!box) return;
  QKC.heatmap(box, { x: ['0', '1', '2', '3', '4', '5'], y: ['0', '1', '2', '3', '4', '5'], data: data, min: 0, fmt: function (v) { return num(v, 1) + '%'; }, xName: away.team + ' goals', yName: home.team + ' goals', label: 'Score probabilities' });
}

// ── directory ─────────────────────────────────────────────────────────────

function dirNav(tab) {
  return FB.subnav([['#/clubs', 'Clubs on one scale', 'clubs'], ['#/clubs/leagues', 'Leagues', 'leagues'], ['#/clubs/nations', 'National teams', 'nations'], ['#/clubs/pricer', 'If they met', 'pricer']], tab, 'Clubs views');
}
function findBox() {
  return '<div class="fb-cl-find"><input class="qk-input" id="cl-find" type="search" placeholder="Jump to any club or national team…" aria-label="Find a club or national team" autocomplete="off"><ul id="cl-find-r" class="fb-cl-find-r" hidden></ul></div>';
}
function wireFind(el) {
  var input = el.querySelector('#cl-find'), out = el.querySelector('#cl-find-r');
  if (!input) return;
  var norm = function (s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); };
  input.addEventListener('input', function () {
    var q = norm(input.value).trim();
    if (q.length < 2) { out.hidden = true; out.innerHTML = ''; return; }
    FB.clubsIndex().then(function (ci) {
      var hits = ci.list.map(function (r) { var n = norm(r.name), k = n.indexOf(q); return k < 0 ? null : [k === 0 ? 0 : n.charAt(k - 1) === ' ' ? 1 : 2, r.home ? 0 : 1, -(r.comps || []).length, r]; })
        .filter(Boolean).sort(function (a, b) { return a[0] - b[0] || a[1] - b[1] || a[2] - b[2]; }).slice(0, 10);
      out.innerHTML = hits.length ? hits.map(function (h) {
        var r = h[3];
        return '<li><a href="' + esc(FB.href.club(r.id)) + '">' + FB.crest(r.id, r.name, 'sm') + '<span class="n">' + esc(r.name) + '</span><span class="s">' + esc(r.national ? 'National team' : (r.home ? FB.compName(r.home, true) : (r.country || 'Club'))) + '</span></a></li>';
      }).join('') : '<li class="none">No club or national team matches.</li>';
      out.hidden = false;
    });
  });
}

FB.route('clubs', function (el, p) {
  var tab = p.tab || 'clubs';
  if (['clubs', 'leagues', 'nations', 'pricer'].indexOf(tab) < 0) tab = 'clubs';
  el.innerHTML = FB.pageHead('Clubs', tab === 'nations' ? 'National teams' : tab === 'pricer' ? 'If they met' : tab === 'leagues' ? 'Leagues on one scale' : 'Clubs on one scale',
    tab === 'nations' ? 'Every national team on the international model: one Dixon-Coles fit over tournaments, qualifiers and the Nations Leagues.'
      : 'One pooled Dixon-Coles fit puts every club of every league on the same scale: cup matches between leagues are the bridges. Open any club for its page across every competition and season.',
    findBox()) + dirNav(tab) + '<div id="cl-dir">' + FB.loading('lines', 6) + '</div>';
  wireFind(el);
  if (tab === 'nations') return drawNations(el, p.query || {});
  return FB.load('pool.json').then(function (pool) {
    if (!FB.alive(el)) return;
    var box = el.querySelector('#cl-dir');
    if (!pool || !(pool.clubs || []).length) { box.innerHTML = FB.empty('No pooled model this run', 'The cross-league fit is rebuilt every hour.'); return; }
    if (tab === 'leagues') drawLeagues(box, pool);
    else if (tab === 'pricer') drawPricer(box, pool, p.query || {});
    else drawPool(box, pool, p.query || {});
  });
});

function drawPool(box, pool, q) {
  /* clubs with no rated match yet (cup entrants seen only in a draw) carry the prior, not a measured rating: they are
     left out of the ranking, which is renumbered over the measured clubs */
  var all = pool.clubs.slice().sort(function (a, b) { return (a.rank || 9999) - (b.rank || 9999); });
  var clubs = all.filter(function (c) { return c.in_league || (c.played || 0) > 0; });
  var unrated = all.length - clubs.length;
  clubs = clubs.map(function (c, i) { return FB.merge(c, { rank: i + 1 }); });
  var leagues = {};
  clubs.forEach(function (c) { if (c.comp) leagues[c.comp] = c.comp_name || FB.compName(c.comp); });
  var lopts = [['', 'All competitions']].concat(Object.keys(leagues).sort(function (a, b) { return String(leagues[a]).localeCompare(String(leagues[b])); }).map(function (k) { return [k, leagues[k]]; }));
  var blocks = Array.from(new Set(clubs.map(function (c) { return c.block; }).filter(Boolean))).sort();
  box.innerHTML = FB.note('<b>One scale for every club.</b> The rating is the points a game we would expect a club to take against an average side from the whole pool, at a neutral ground. Clubs from different continents rarely meet, so the gaps between continents are the least certain numbers here.') +
    '<div class="fb-mt"></div>' + FB.grid(
    FB.card('Every club', clubs.length + ' clubs with a rated match' + (unrated ? ' (' + unrated + ' cup entrants with none yet are left out: they carry the prior)' : '') + ' · home advantage ' + num(pool.model.home_adv, 2) + ' goals (log scale) · ρ ' + num(pool.model.rho, 3),
      FB.toolbar([FB.field('Competition', FB.select('cl-lg', lopts, q.lg || '', 'Competition')), FB.field('Block', FB.select('cl-bl', [['', 'All blocks']].concat(blocks.map(function (b) { return [b, b]; })), q.bl || '', 'Block')),
        FB.field('Club', '<input class="qk-input" id="cl-q" type="search" placeholder="Filter by name" value="' + esc(q.q || '') + '">')], 'fb-cl-ftb') +
      '<div id="cl-pool"></div><p class="fb-cap" id="cl-pool-cap"></p>', { span: 12 }) +
    FB.card('The strongest 25', 'Expected points per game against the pool-average club at a neutral venue.', FB.chartBox('cl-top', 620, 'The strongest 25 clubs'), { span: 7 }) +
    FB.card('Attack against defence', 'Each club\'s scoring and conceding rates against the pool average; top right is strong at both ends. The 60 strongest.', FB.chartBox('cl-ad', 620, 'Attack against defence'), { span: 5 })
  );
  function draw() {
    var lg = box.querySelector('#cl-lg').value, bl = box.querySelector('#cl-bl').value, qq = box.querySelector('#cl-q').value.trim().toLowerCase();
    FB.setQuery({ lg: lg || null, bl: bl || null, q: qq || null });
    var list = clubs.filter(function (c) { return (!lg || c.comp === lg) && (!bl || c.block === bl) && (!qq || String(c.team).toLowerCase().indexOf(qq) >= 0); });
    var LIM = lg || qq || bl ? 500 : 150;
    board(box.querySelector('#cl-pool'), [
      { key: 'rank', label: '#', num: true },
      { key: 'team', label: 'Club', type: 'entity', mark: function (r) { return clubMark(r.team_id, r.team); }, href: function (r) { return FB.href.club(r.team_id); } },
      { key: 'comp_name', label: 'Competition', fmt: function (v, r) { return FB.compLink(r.comp, { short: true }); } },
      { key: 'block', label: 'Block' },
      { key: 'strength', label: 'Rating', type: 'bar', fmt: function (v) { return '<b>' + num(v, 2) + '</b>'; }, tip: 'Our rating: expected points per game against the pool-average club, neutral venue' },
      { key: 'xg_for', label: 'xG for', num: true, d: 2, tip: 'Expected goals against the pool-average defence' },
      { key: 'xg_against', label: 'xG ag.', num: true, d: 2 },
      { key: 'attack', label: 'Att', num: true, fmt: function (v) { return signed(v, 2); } },
      { key: 'defence', label: 'Def', num: true, fmt: function (v) { return signed(v, 2); }, tip: 'Lower is better (fewer goals conceded)' },
      { key: 'elo', label: 'Elo', num: true, d: 0 },
      { key: 'table_rank', label: 'Pos', num: true },
      { key: 'ppg', label: 'Form', sort: false, fmt: function (v, r) { return r.form_results ? QK.formDots(r.form_results) : '—'; } },
      { key: 'luck', label: 'Luck', num: true, fmt: function (v) { return isNum(v) ? signed(v, 1) : '—'; }, tip: 'Points above what the xG deserved this season' }
    ], list.slice(0, LIM), { maxHeight: 560, caption: 'Clubs on the pooled scale', sort: { key: 'rank', dir: 'asc' } });
    FB.set('cl-pool-cap', list.length > LIM ? 'Showing the ' + LIM + ' strongest of ' + list.length + '; filter by competition or name for the rest.' : list.length + ' clubs.');
  }
  ['cl-lg', 'cl-bl'].forEach(function (id) { box.querySelector('#' + id).addEventListener('change', draw); });
  box.querySelector('#cl-q').addEventListener('input', draw);
  draw();
  /* the chart ranks measured clubs: cup entrants with no matches yet carry the prior */
  var top = clubs.slice(0, 25);
  QKC.bar(box.querySelector('#cl-top'), {
    horizontal: true, labels: true, labelWidth: 170, fmt: function (v) { return num(v, 2); }, min: 1.4, valName: 'Expected points per game',
    cats: top.map(function (c) { return c.team + ' · ' + (c.comp_name || ''); }), series: [{ name: 'Strength', data: top.map(function (c) { return c.strength; }) }],
    colors: top.map(function () { return QK.cssVar('--signal'); }), hrefs: top.map(function (c) { return FB.href.club(c.team_id); }), label: 'Strongest 25 clubs on the pooled scale', catName: 'Club'
  });
  var sixty = clubs.slice(0, 60);
  QKC.scatter(box.querySelector('#cl-ad'), {
    points: sixty.map(function (c) { return { x: c.xg_for, y: c.xg_against, name: c.team + ' (' + (c.comp_name || '') + ')', label: c.team, href: FB.href.club(c.team_id) }; }),
    xName: 'xG for per match', yName: 'xG against per match', yMin: undefined, labelTop: 10, xFmt: function (v) { return num(v, 1); }, yFmt: function (v) { return num(v, 1); },
    label: 'Attack against defence, the 60 strongest clubs'
  });
}

function drawLeagues(box, pool) {
  var L = pool.leagues || {};
  var rows = Object.keys(L).map(function (s) { return FB.merge(L[s], { slug: s }); }).sort(function (a, b) { return a.rank - b.rank; });
  var bridges = pool.bridges || {};
  var bk = Object.keys(bridges).sort(function (x, y) { return bridges[y] - bridges[x]; });
  box.innerHTML = FB.grid(
    FB.card('League strength', 'Mean strength of each league\'s clubs: expected points per game against the pool-average club.', FB.chartBox('cl-lgbar', Math.max(260, rows.length * 24), 'League strength'), { span: 5 }) +
    FB.card('Leagues on one scale', rows.length + ' competitions in the pooled fit.', '<div id="cl-lgt"></div>', { span: 7, flush: true }) +
    FB.card('How sure is the scale?', '', FB.note('<span><b>Between continents</b> the fit has only these matches to go on: ' + (bk.length ? bk.map(function (k) { return esc(k.replace('|', ' – ')) + ' <b>' + bridges[k] + '</b>'; }).join(' · ') : 'none') +
      '. Within a block (Europe through the UEFA cups, South America through CONMEBOL\'s, North America through CONCACAF\'s, Asia through the AFC\'s) the scale is well identified; across blocks the Club World Cup and the Intercontinental Cup are the only bridges, so read cross-continent ranks as the model\'s best guess with wide error.'), { span: 12 })
  );
  board(box.querySelector('#cl-lgt'), [
    { key: 'rank', label: '#', num: true },
    { key: 'name', label: 'League', sticky: true, fmt: function (v, r) { return FB.comp(r.slug) ? FB.compLink(r.slug) : esc(v); } },
    { key: 'block', label: 'Block' },
    { key: 'n_clubs', label: 'Clubs', num: true },
    { key: 'strength', label: 'Rating', type: 'bar', fmt: function (v) { return '<b>' + num(v, 3) + '</b>'; }, tip: 'Mean rating of the league\'s clubs: expected points per game against the pool-average club' },
    { key: 'attack', label: 'Att', num: true, fmt: function (v) { return signed(v, 2); } },
    { key: 'defence', label: 'Def', num: true, fmt: function (v) { return signed(v, 2); } },
    { key: 'factor_att', label: 'Scoring factor', num: true, d: 3, tip: 'Multiplier on a player\'s attacking rates from this league: how much harder it is to score here than against the pool average' },
    { key: 'best', label: 'Best club', fmt: function (v, r) { return esc(v || '—') + (r.best_rank ? ' <span class="qk-muted fb-num">#' + r.best_rank + '</span>' : ''); } },
    { key: 'connection', label: 'Bridge', num: true, fmt: function (v) { return v + (v < 20 ? ' ' + FB.badge('weak', '', 'Few cup matches connect this league to the rest: a less certain scale') : ''); }, tip: 'Cup matches connecting this league to the pool' }
  ], rows, { caption: 'Leagues on one scale', sort: { key: 'rank', dir: 'asc' } });
  QKC.bar(box.querySelector('#cl-lgbar'), {
    horizontal: true, labels: true, labelWidth: 140, fmt: function (v) { return num(v, 2); }, min: 0.8, valName: 'Expected points per game', catName: 'League',
    cats: rows.map(function (r) { return r.name; }), series: [{ name: 'Rating', data: rows.map(function (r) { return r.strength; }) }], colors: rows.map(function () { return QK.cssVar('--signal'); }),
    hrefs: rows.map(function (r) { return FB.comp(r.slug) ? FB.href.comp(r.slug) : undefined; }), label: 'League strength on the pooled scale'
  });
}

function pricerControls(prefix, teams, ia, ib, venue) {
  var opts = teams.map(function (t, i) { return [i, t._label || t.team]; });
  return FB.toolbar([FB.field('Home side', FB.select(prefix + '-a', opts, ia, 'Home side', 'fb-cl-wide')), FB.field('Away side', FB.select(prefix + '-b', opts, ib, 'Away side', 'fb-cl-wide')),
    FB.field('Venue', FB.select(prefix + '-v', [['home', 'First side at home'], ['neutral', 'Neutral venue']], venue, 'Venue'))], 'fb-cl-ptb');
}
function wirePricer(box, prefix, teams, model, onChange) {
  function show() {
    var a = teams[parseInt(box.querySelector('#' + prefix + '-a').value, 10)], b = teams[parseInt(box.querySelector('#' + prefix + '-b').value, 10)];
    var neutral = box.querySelector('#' + prefix + '-v').value === 'neutral';
    if (!a || !b) return;
    box.querySelector('#' + prefix + '-out').innerHTML = chanceHTML(prefix + '-grid', a, b, model, neutral);
    drawScoreGrid(box, prefix + '-grid', a, b, model, neutral);
    if (onChange) onChange(a, b, neutral);
  }
  ['-a', '-b', '-v'].forEach(function (s) { box.querySelector('#' + prefix + s).addEventListener('change', show); });
  show();
}
function drawPricer(box, pool, q) {
  var teams = pool.clubs.slice().sort(function (a, b) { return String(a.team).localeCompare(String(b.team)); }).map(function (c) { return FB.merge(c, { _label: c.team + ' (' + (c.comp_name || c.comp) + ')' }); });
  var idx = function (tid, dflt) { for (var i = 0; i < teams.length; i++) if (String(teams[i].team_id) === String(tid)) return i; return dflt; };
  var byRank = pool.clubs.slice().sort(function (a, b) { return a.rank - b.rank; });
  var ia = idx(q.a, idx((byRank[0] || {}).team_id, 0)), ib = idx(q.b, idx((byRank[1] || {}).team_id, 1));
  box.innerHTML = FB.card('Any two clubs, by the numbers', 'Our chances from the pooled Dixon-Coles fit: the same goal rates behind every league\'s forecasts, on one scale.',
    pricerControls('cp', teams, ia, ib, q.v === 'neutral' ? 'neutral' : 'home') + '<div id="cp-out" class="fb-mt"></div>' +
    '<p class="fb-cap">Our forecast for a match that may never happen. Between continents the scale rests on few matches (see Leagues), so read those chances loosely.</p>');
  wirePricer(box, 'cp', teams, pool.model, function (a, b, neutral) { FB.setQuery({ a: a.team_id, b: b.team_id, v: neutral ? 'neutral' : null }); });
}

function drawNations(el, q) {
  return Promise.all([FB.load('nations.json'), FB.load('hub.json'), FB.clubsIndex()]).then(function (arr) {
    if (!FB.alive(el)) return;
    var n = arr[0], hub = arr[1], ci = arr[2];
    var box = el.querySelector('#cl-dir');
    var teams = (n || {}).teams || [];
    if (!teams.length) { box.innerHTML = FB.empty('No international fit yet', (n || {}).note || 'The national-team stores fill on the next fetch.'); return; }
    var tidOf = {};
    ci.list.forEach(function (r) { if (r.national) tidOf[r.name] = r.id; });
    var confs = Array.from(new Set(teams.map(function (t) { return t.confederation; }).filter(Boolean))).sort();
    var alpha = teams.slice().sort(function (a, b) { return a.team.localeCompare(b.team); });
    var ia = 0, ib = 1;
    alpha.forEach(function (t, i) { if (t.team === teams[0].team) ia = i; if (t.team === teams[1].team) ib = i; });
    box.innerHTML = FB.grid(
      FB.card('Every national team', teams.length + ' teams · ' + esc(n.note || ''), FB.toolbar([FB.field('Confederation', FB.select('cn-conf', [['', 'All']].concat(confs.map(function (c) { return [c, c]; })), q.conf || '', 'Confederation')),
        FB.field('Team', '<input class="qk-input" id="cn-q" type="search" placeholder="Filter by name">')], 'fb-cl-ftb') + '<div id="cn-t"></div>', { span: 7 }) +
      FB.card('The strongest 25', 'Expected points per game against the average national team, neutral venue.', FB.chartBox('cn-top', 620, 'Strongest national teams'), { span: 5 }) +
      FB.card('If they met', 'Our chances for any two national teams, from the international fit.', pricerControls('np', alpha, ia, ib, 'neutral') + '<div id="np-out" class="fb-mt"></div>', { span: 7 }) +
      FB.card('Next internationals', 'Across every national-team competition followed, with our home / draw / away chance.', '<div id="cn-fx" class="fb-fxlist"></div>', { span: 5 })
    );
    function draw() {
      var conf = box.querySelector('#cn-conf').value, qq = box.querySelector('#cn-q').value.trim().toLowerCase();
      FB.setQuery({ conf: conf || null });
      board(box.querySelector('#cn-t'), [
        { key: 'rank', label: '#', num: true },
        { key: 'team', label: 'Team', type: 'entity', mark: function (r) { return clubMark(tidOf[r.team], r.team); }, href: function (r) { return tidOf[r.team] ? FB.href.club(tidOf[r.team]) : null; } },
        { key: 'confederation', label: 'Conf.' },
        { key: 'played', label: 'Played', num: true },
        { key: 'strength', label: 'Rating', type: 'bar', fmt: function (v) { return '<b>' + num(v, 2) + '</b>'; }, tip: 'Our rating: expected points per game against the average national team, neutral venue' },
        { key: 'attack', label: 'Att', num: true, fmt: function (v) { return signed(v, 2); } },
        { key: 'defence', label: 'Def', num: true, fmt: function (v) { return signed(v, 2); } },
        { key: 'elo', label: 'Elo', num: true, d: 0 }
      ], teams.filter(function (t) { return (!conf || t.confederation === conf) && (!qq || t.team.toLowerCase().indexOf(qq) >= 0); }), { maxHeight: 520, caption: 'National teams', sort: { key: 'rank', dir: 'asc' } });
    }
    box.querySelector('#cn-conf').addEventListener('change', draw);
    box.querySelector('#cn-q').addEventListener('input', draw);
    draw();
    var top = teams.slice(0, 25);
    QKC.bar(box.querySelector('#cn-top'), {
      horizontal: true, labels: true, labelWidth: 120, min: 1.4, valName: 'Expected points per game', catName: 'National team', fmt: function (v) { return num(v, 2); },
      cats: top.map(function (t) { return t.team; }), series: [{ name: 'Rating', data: top.map(function (t) { return t.strength; }) }],
      colors: top.map(function () { return QK.cssVar('--signal'); }), hrefs: top.map(function (t) { return tidOf[t.team] ? FB.href.club(tidOf[t.team]) : undefined; }), label: 'Strongest national teams'
    });
    wirePricer(box, 'np', alpha, n.model);
    var all = [];
    var days = (hub || {}).days || {};
    Object.keys(days).forEach(function (k) { all = all.concat(days[k] || []); });
    all = all.concat((hub || {}).upcoming || []);
    var seen = {};
    var now = Date.now() - 3 * 3600e3;
    var list = all.filter(function (m) { var t = FB.parseDate(m.date); return m.family === 'international' && m.status !== 'finished' && t && t >= now; })
      .filter(function (m) { var k = m.comp + ':' + m.id; if (seen[k]) return false; seen[k] = 1; return true; })
      .sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); }).slice(0, 20);
    box.querySelector('#cn-fx').innerHTML = list.length ? list.map(function (m) { return FB.fixtureRow(m, { date: true, comp: true }); }).join('') : FB.empty('No internationals scheduled', 'The next window\'s fixtures appear once they are published.');
  });
}

// ── the club page ─────────────────────────────────────────────────────────

/* A club's season frame from its rows: split ("2026/27") or calendar ("2026"). */
function frameOf(doc) {
  var split = 0, cal = 0;
  (doc.years || []).forEach(function (y) { if (String(y.era).indexOf('/') >= 0) split++; else cal++; });
  return split >= cal && split ? 'split' : 'calendar';
}
function eraFromDate(frame, date) {
  var d = FB.parseDate(date);
  if (!d) return '';
  var y = d.getUTCFullYear(), m = d.getUTCMonth() + 1;
  if (frame === 'calendar') return String(y);
  var s = m >= 7 ? y : y - 1;
  return s + '/' + String((s + 1) % 100).replace(/^(\d)$/, '0$1');
}
function prep(doc) {
  var frame = frameOf(doc);
  var seasons = (doc.seasons || []).map(function (s) {
    return FB.merge(s, { kind: s.kind || FB.kindOf(s.comp), cname: FB.compName(s.comp), cshort: FB.compName(s.comp, true) });
  });
  var bySid = {};
  seasons.forEach(function (s) { bySid[s.comp + '|' + s.sid] = s; });
  var matches = (doc.matches || []).map(function (m) {
    var s = bySid[m.comp + '|' + m.sid];
    return FB.merge(m, { kind: FB.kindOf(m.comp), era: s ? s.era : eraFromDate(frame, m.date) });
  });
  var compsSeen = {};
  seasons.concat(matches).forEach(function (r) { if (r.comp && !compsSeen[r.comp]) compsSeen[r.comp] = { slug: r.comp, name: FB.compName(r.comp), kind: FB.kindOf(r.comp) }; });
  var comps = Object.keys(compsSeen).map(function (k) { return compsSeen[k]; }).sort(function (a, b) { return (FB.KIND_ORDER[a.kind] - FB.KIND_ORDER[b.kind]) || a.name.localeCompare(b.name); });
  var eras = Array.from(new Set(seasons.map(function (s) { return s.era; }).concat(matches.map(function (m) { return m.era; })).concat((doc.years || []).map(function (y) { return y.era; })).filter(Boolean)))
    .sort(function (a, b) { return FB.eraKey(b) - FB.eraKey(a); });
  var live = seasons.filter(function (s) { return s.source === 'live'; });
  var cur = (doc.squad || {}).era || (live[0] || {}).era || eras[0] || '';
  var valueLeague = live.filter(function (s) { return s.kind === 'league' && VALUE_LEAGUES.indexOf(s.comp) >= 0; })[0];
  return { doc: doc, tid: String(doc.id), frame: frame, seasons: seasons, matches: matches, comps: comps, eras: eras, cur: cur, live: live, valueLeague: valueLeague ? valueLeague.comp : null };
}
/* A club match -> a fixture row (home/away from the fixture's point of view). */
function asFixture(C, m) {
  var me = { name: C.doc.name, id: C.doc.id }, op = { name: m.opp, id: m.opp_tid };
  var h = m.home ? me : op, a = m.home ? op : me;
  var xg = m.xg ? (m.home ? m.xg : [m.xg[1], m.xg[0]]) : null;
  return { id: m.id, comp: m.comp, date: m.date, status: m.status, round: m.round, stage: m.stage, detail: m.detail,
    home: h.name, away: a.name, home_id: h.id, away_id: a.id, hs: m.home ? m.gf : m.ga, as: m.home ? m.ga : m.gf, xg: xg, model: m.model };
}
function finishText(s) {
  var isLeague = s.kind === 'league';
  var agrees = has(s.pts) && has(s.w) && s.pts === 3 * s.w + s.d;
  var inPhase = !s.stage || ['league', 'group', 'qualifying'].indexOf(s.stage) >= 0;
  var stage = s.stage && !inPhase ? FB.stageText(s.stage) : '';
  var grp = s.group ? String(s.group).replace(/^.*,\s*/, '') : '';
  var finish;
  if (isLeague) {
    finish = has(s.pos) ? FB.ordinal(s.pos) + (grp ? ' · ' + grp : '') : '';
    if (stage) finish = (finish ? finish + ' · ' : '') + stage;
    else if (s.pos === 1 && !grp && s.source !== 'live') finish += ' · champions';
  } else {
    var table = has(s.pos) && s.comp !== 'friendlies' ? FB.ordinal(s.pos) + (grp ? ' in ' + (/^[A-Z]\d?$/.test(grp) ? 'group ' + grp : grp) : (s.kind === 'continental_club' ? ' in the league phase' : '')) + (has(s.pts) && !agrees ? ', ' + s.pts + ' pts' : '') : '';
    finish = [stage, table].filter(Boolean).join(' · ');
    if (!finish && s.stage === 'qualifying') finish = 'Qualifying';
  }
  return finish || '—';
}
/* Archive rows carry zeros for what the archive does not know: treat them as unknown. */
function clean(s) { return (!s.played && s.source !== 'live') ? FB.merge(s, { played: null, w: null, d: null, l: null, gf: null, ga: null }) : s; }
function seasonHref(s) {
  var c = FB.comp(s.comp);
  if (!c) return null;
  var cur = FB.currentSeason(c);
  return FB.href.comp(s.comp, 'table', String(s.sid) === cur.sid ? null : { s: s.sid });
}
/* Year by year: the payload's own years when the whole club is shown, else summed from the filtered rows. */
function yearRows(C, q) {
  if (!q.c && (C.doc.years || []).length) return C.doc.years.map(function (y) { return FB.merge(y, { partial: y.record === 'partial' }); });
  var yb = {};
  C.seasons.filter(function (s) { return !q.c || s.comp === q.c; }).forEach(function (s0) {
    var s = clean(s0);
    if (!s.era) return;
    var y = yb[s.era] || (yb[s.era] = { era: s.era, comps: 0, played: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0, partial: false, won: [] });
    y.comps += 1;
    if (s.stage === 'winner') y.won.push(s.comp);
    if (!has(s.w)) { if (s0.played) y.partial = true; return; }
    ['played', 'w', 'd', 'l', 'gf', 'ga'].forEach(function (k) { y[k] += Number(s[k]) || 0; });
  });
  return Object.keys(yb).map(function (k) { return yb[k]; }).sort(function (a, b) { return FB.eraKey(b.era) - FB.eraKey(a.era); });
}

FB.route('club', function (el, p) {
  var tid = String(p.tid || '');
  var q = FB.merge(p.query || {}, {});
  el.innerHTML = FB.loading('lines', 8);
  return Promise.all([FB.load('clubs/' + tid + '.json'), FB.clubsIndex()]).then(function (arr) {
    if (!FB.alive(el)) return;
    var doc = arr[0];
    if (!doc || doc.id === undefined) {
      el.innerHTML = FB.pageHead('Clubs', 'Club not found', 'There is no club or national team with id ' + esc(tid) + ' in the stores.') + '<p><a class="qk-btn" href="#/clubs">All clubs →</a></p>';
      return;
    }
    var C = prep(doc);
    if (q.c && !C.comps.some(function (c) { return c.slug === q.c; })) delete q.c;
    if (q.e && C.eras.indexOf(q.e) < 0) delete q.e;
    if (q.c && FB.comp(q.c)) FB.setCompPicker(q.c);
    document.title = doc.name + ' · The Quant Footballer';
    var tabs = ['overview', 'seasons', 'squad', 'matches'].concat(C.valueLeague ? ['transfers'] : []);
    var tab = tabs.indexOf(q.tab) >= 0 ? q.tab : 'overview';
    el.innerHTML = hero(C) + '<div class="fb-cl-bar">' + FB.subnav(tabs.map(function (t) {
      return [FB.href.club(tid, FB.merge(q, { tab: t === 'overview' ? null : t })), { overview: 'Overview', seasons: 'Season by season', squad: doc.national ? 'Call-up' : 'Squad', matches: 'Matches', transfers: 'Moves & needs' }[t], t];
    }), tab, 'Club views') + filterBar(C, q, tab) + '</div><div id="cl-body" class="fb-cl-body"></div>';
    wireFilter(el, C);
    var body = el.querySelector('#cl-body');
    if (tab === 'seasons') return drawSeasons(body, C, q);
    if (tab === 'squad') return drawSquad(body, C, q);
    if (tab === 'matches') return drawMatches(body, C, q);
    if (tab === 'transfers') return drawTransfers(body, C);
    return drawOverview(body, C, q);
  });
});

function hero(C) {
  var doc = C.doc;
  var home = doc.home ? FB.comp(doc.home) : null;
  var years = doc.years || [];
  var trophies = 0;
  years.forEach(function (y) { trophies += (y.won || []).length; });
  var curY = years.filter(function (y) { return y.era === C.cur; })[0] || years[0] || null;
  var sq = (doc.squad || {}).players || [];
  var mv = 0, nmv = 0;
  sq.forEach(function (x) { if (isNum(x.mv)) { mv += x.mv; nmv++; } });
  var ages = sq.map(function (x) { return x.age; }).filter(isNum);
  /* v4 chips on the hero (QK.playerHeader meta: HTML items keep their links) */
  var meta = [];
  if (FB.hasCrest(doc.id)) meta.push('<span class="fb-cl-crest">' + FB.crest(doc.id, doc.name, 'sm') + '</span>');
  if (doc.national) meta.push('<span>National team</span>');
  if (home) meta.push('<span>' + FB.compLink(home.slug) + '</span>');
  if (doc.country && !doc.national) meta.push('<span>' + esc(doc.country) + '</span>');
  if (nmv) meta.push('<span>Squad value <b>' + FB.money(mv) + '</b></span>');
  if (ages.length) meta.push('<span>Average age <b>' + num(ages.reduce(function (a, b) { return a + b; }, 0) / ages.length, 1) + '</b></span>');
  var live = Array.from(new Set(C.live.map(function (s) { return s.comp; })));
  var pool = doc.pool || {};
  var tiles = [];
  /* a club with no finished match in the stores this season carries the prior, not a measured rating: no tile */
  var rated = C.matches.some(function (m) { return m.status === 'finished' && m.era === C.cur; });
  if (isNum(pool.strength) && rated) tiles.push(FB.kpi('Our rating', num(pool.strength, 2), { signal: true, unit: 'PPG', sub: 'on one scale across every league', href: '#/clubs', tip: 'Expected points per game against the pool-average club at a neutral venue, from our pooled Dixon-Coles fit across every league' }));
  if (curY && curY.played) tiles.push(FB.kpi(curY.era + ' record', curY.w + '-' + curY.d + '-' + curY.l, { text: false, sub: 'won, drawn, lost · ' + curY.played + ' played' }));
  if (curY && curY.played) tiles.push(FB.kpi('Points a game', num(ppgOf(curY), 2), { sub: 'every competition, ' + esc(curY.era) }));
  tiles.push(FB.kpi('Trophies on record', String(trophies), { sub: years.length + ' season' + (years.length === 1 ? '' : 's') + ' in the data' }));
  /* "The short version" in plain English, the explain strip under the hero */
  var short = '';
  if (curY && curY.played) short = doc.name + ' have won ' + curY.w + ', drawn ' + curY.d + ' and lost ' + curY.l + ' of ' + curY.played + ' in ' + curY.era + (curY.comps > 1 ? ' across ' + curY.comps + ' competitions' : '') + ', ' + num(ppgOf(curY), 2) + ' points a game.';
  if (isNum(pool.strength) && rated) short += (short ? ' ' : '') + 'Our rating puts them at ' + num(pool.strength, 2) + ' points a game against an average side anywhere' + (isNum(pool.rank) ? ', ' + FB.ordinal(pool.rank) + ' of every ' + (doc.national ? 'national team' : 'club') + ' on one scale' : '') + '.';
  if (curY && curY.played && curY.played < 8) short += ' Early days: ' + curY.played + ' matches is a small sample.';
  /* v4 (Broadcast): the club as the full-bleed team-colour hero (QK.playerHeader: the club's kit colour and its
     alternate from clubs_index.json, else cobalt; the club's short code outlined where a player's number goes, the name
     in Bebas, chips), the black strip of its numbers, and "The short version" as the explain strip */
  return FB.crumb([['#/clubs', doc.national ? 'National teams' : 'Clubs'], home ? [FB.href.comp(home.slug), home.name] : null, doc.name].filter(Boolean)) + QK.playerHeader({ name: doc.name, face: FB.clubCode(doc.name), colour: FB.clubColour(doc.id), alt: FB.clubAlt(doc.id),
    kicker: (doc.national ? 'National team' : 'Club') + (live.length ? ' · this season in ' + live.map(function (s) { return FB.compName(s, true); }).join(', ') : ''),
    meta: meta, strip: tiles, short: short || null });
}
function filterBar(C, q, tab) {
  if (tab === 'squad' || tab === 'transfers') return '';
  var copts = [['', 'Every competition']].concat(C.comps.map(function (c) { return [c.slug, c.name]; }));
  var eopts = [['', 'Every season']].concat(C.eras.map(function (e) { return [e, e + (e === C.cur ? ' (this season)' : '')]; }));
  return '<div class="fb-cl-filter">' + FB.select('cl-fc', copts, q.c || '', 'Competition') + (tab === 'overview' ? '' : FB.select('cl-fe', eopts, q.e || '', 'Season')) +
    (q.c || q.e ? '<a class="qk-btn fb-cl-clear" href="' + esc(FB.href.club(C.tid, q.tab ? { tab: q.tab } : null)) + '">Clear</a>' : '') + '</div>';
}
function wireFilter(el, C) {
  var c = el.querySelector('#cl-fc'), e = el.querySelector('#cl-fe');
  if (c) c.addEventListener('change', function () { FB.setQuery({ c: c.value || null }, true); });
  if (e) e.addEventListener('change', function () { FB.setQuery({ e: e.value || null }, true); });
}
function keepFn(q) { return function (r) { return (!q.c || r.comp === q.c) && (!q.e || r.era === q.e); }; }

/* ── overview */
function recordTiles(ms) {
  var done = ms.filter(function (m) { return m.status === 'finished' && isNum(m.gf) && isNum(m.ga); });
  var w = done.filter(function (m) { return m.gf > m.ga; }).length, dr = done.filter(function (m) { return m.gf === m.ga; }).length, l = done.length - w - dr;
  var gf = FB.sum(done, 'gf'), ga = FB.sum(done, 'ga');
  var wx = done.filter(function (m) { return m.xg && isNum(m.xg[0]); });
  var xgf = wx.reduce(function (s, m) { return s + m.xg[0]; }, 0), xga = wx.reduce(function (s, m) { return s + (m.xg[1] || 0); }, 0);
  var cs = done.filter(function (m) { return m.ga === 0; }).length;
  var form = done.slice(0, 5).map(function (m) { return resCls(m.gf, m.ga); }).reverse();
  return FB.kpis([
    FB.kpi('Played', String(done.length), { sub: ms.length - done.length ? (ms.length - done.length) + ' still to play' : 'matches in the stores' }),
    FB.kpi('Record', w + '-' + dr + '-' + l, { sub: done.length ? pct(w / done.length) + ' won' : '' }),
    FB.kpi('Form', form.length ? QK.formDots(form) : '—', { text: false, sub: 'last ' + form.length + ', oldest first' }),
    FB.kpi('Goals', gf + '–' + ga, { sub: done.length ? num(gf / done.length, 2) + '–' + num(ga / done.length, 2) + ' a match' : '' }),
    FB.kpi('xG a match', wx.length ? num(xgf / wx.length, 2) + '–' + num(xga / wx.length, 2) : '—', { sub: wx.length ? wx.length + ' matches with xG' : 'no xG in the filter', tip: 'Expected goals for and against per match, from shot quality' }),
    FB.kpi('Points a game', done.length ? num((3 * w + dr) / done.length, 2) : '—', { sub: 'every match in the filter' }),
    FB.kpi('Clean sheets', String(cs), { sub: done.length ? pct(cs / done.length) + ' of matches' : '' })
  ]);
}
function drawOverview(body, C, q) {
  var doc = C.doc;
  var ms = C.matches.filter(keepFn(FB.merge(q, { e: q.e || C.cur })));
  var cdossier = q.c && FB.comp(q.c) && C.live.some(function (s) { return s.comp === q.c; });
  body.innerHTML = '<div class="qk-kicker fb-cl-k">' + esc(q.e || C.cur) + (q.c ? ' · ' + esc(FB.compName(q.c)) : ' · every competition') + '</div>' + recordTiles(ms) +
    (cdossier ? '<div id="cl-dossier" class="fb-sec"></div>' : '') +
    '<section class="fb-sec" id="cl-perf"></section>' +
    '<section class="fb-sec">' + FB.card('Year by year', (q.c ? 'In ' + esc(FB.compName(q.c)) + ' only. ' : 'Every competition summed per season, ') + 'oldest to newest: results by colour, points per game on the line. ' +
      (C.frame === 'calendar' ? 'Seasons are calendar years.' : 'Seasons run July to June; summer tournaments close the season they end.'),
      FB.chartBox('cl-yy', 300, 'Results by season') + '<div id="cl-yyt" class="fb-mt"></div>') + '</section>' +
    '<section class="fb-sec">' + FB.grid(
      FB.card('This season, competition by competition', esc(C.cur) + ' · finish, record and our rating.', '<div id="cl-now"></div>', { span: 7, flush: true, foot: '<span></span><a href="' + esc(FB.href.club(C.tid, { tab: 'seasons' })) + '">Every season →</a>' }) +
      FB.card('Next and last', 'Kick-off in your time zone; before a match, our chance for each side and the draw.', '<div id="cl-nl" class="fb-cl-gcs"></div>', { span: 5, foot: '<span></span><a href="' + esc(FB.href.club(C.tid, FB.merge(q, { tab: 'matches' }))) + '">All matches →</a>' })
    ) + '</section>' +
    '<section class="fb-sec">' + FB.grid(
      FB.card('Rating through the season', 'Elo after each match' + (doc.home ? ' in ' + esc(FB.compName(doc.home)) : '') + '.', FB.chartBox('cl-elo', 260, 'Elo through the season'), { span: 6, id: 'cl-elo-card' }) +
      FB.card('Rating by competition', 'This season\'s rating in each competition: expected points a game against an average side there.', FB.chartBox('cl-str', 220, 'Strength by competition'), { span: 6, id: 'cl-str-card' })
    ) + '</section>' +
    (C.valueLeague ? '<section class="fb-sec" id="cl-needs-mini"></section>' : '') +
    '<section class="fb-sec" id="cl-most"></section>';

  drawYears(body, C, q);
  drawNow(body, C);
  if (doc.home === 'liga-argentina') drawArgentina(body.querySelector('#cl-now'), C);
  var nl = C.matches.filter(function (m) { return !q.c || m.comp === q.c; });
  var next = nl.filter(function (m) { return (m.status === 'scheduled' || m.status === 'live') && !FB.staleLive(m); }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); }).slice(0, 2);
  var last = nl.filter(function (m) { return m.status === 'finished'; }).slice(0, 2);
  var gc = function (m) { return FB.matchCard(asFixture(C, m), m.comp, { league: FB.compName(m.comp, true) }); };
  body.querySelector('#cl-nl').innerHTML = (next.length || last.length) ?
    (next.length ? '<div class="qk-kicker fb-cl-k">Next</div>' + next.map(gc).join('') : '') +
    (last.length ? '<div class="qk-kicker fb-cl-k">Last</div>' + last.map(gc).join('') : '')
    : FB.empty('No matches', 'Nothing in the stores for this filter.');
  drawRatings(body, C);
  if (C.valueLeague) FB.load('value/club/' + C.tid + '.json').then(function (d) { if (FB.alive(body)) drawNeedsMini(body.querySelector('#cl-needs-mini'), C, d); });
  drawMost(body.querySelector('#cl-most'), C);
  drawPerformers(body.querySelector('#cl-perf'), C);
  if (cdossier) drawDossier(body.querySelector('#cl-dossier'), C, q.c);
}

function drawYears(body, C, q) {
  var rows = yearRows(C, q);
  var tbl = body.querySelector('#cl-yyt'), box = body.querySelector('#cl-yy');
  if (!rows.length) { box.style.display = 'none'; tbl.innerHTML = FB.empty('No seasons', 'Nothing on record for this filter.'); return; }
  var asc = rows.slice().reverse().filter(function (y) { return y.played; });
  if (asc.length) {
    QKC.mount(box, function (T) {
      var good = QK.cssVar('--st-good'), bad = QK.cssVar('--st-crit');
      var cats = asc.map(function (y) { return y.era; });
      var bar = function (name, k, c) { return { type: 'bar', name: name, stack: 'r', barMaxWidth: 34, data: asc.map(function (y) { return y[k]; }), itemStyle: { color: c } }; };
      var ya = QKC.axis(T, {}), yb = QKC.axis(T, { min: 0, max: 3, split: false });
      var xa = QKC.axis(T, { type: 'category', data: cats, split: false, line: true });
      var gB = 6 + QKC.nameAxis(xa, 'Season', 'bottom'), gT = 34 + QKC.nameAxis(ya, 'Matches', 'side');
      yb.name = 'Points per game'; yb.nameLocation = 'end'; yb.nameGap = 8; yb.nameTextStyle.align = 'right';
      return {
        grid: { left: 8, right: 8, top: gT, bottom: gB, containLabel: true },
        legend: { top: 0, right: 0, icon: 'rect', itemWidth: 10, itemHeight: 10, textStyle: { color: T.ink2 } },
        tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: QKC.hexA(T.ink1, 0.04) } } }),
        xAxis: xa,
        yAxis: [ya, yb],
        series: [bar('Won', 'w', good), bar('Drawn', 'd', QKC.hexA(T.ink3, 0.6)), bar('Lost', 'l', bad),
          { type: 'line', name: 'Points per game', yAxisIndex: 1, data: asc.map(function (y) { return Math.round(ppgOf(y) * 100) / 100; }), symbol: 'circle', symbolSize: 7, lineStyle: { width: 2, color: T.ink1 }, itemStyle: { color: T.ink1, borderColor: T.s1, borderWidth: 2 } }]
      };
    }, { label: 'Wins, draws and losses by season with points per game' });
  } else box.style.display = 'none';
  FB.table(tbl, [
    { key: 'era', label: 'Season', sticky: true, fmt: function (v) { return '<a class="fb-link" href="' + esc(FB.href.club(C.tid, FB.merge(q, { e: v, tab: 'seasons' }))) + '">' + esc(v) + '</a>' + (v === C.cur ? ' ' + FB.badge('now', 'accent') : ''); } },
    { key: 'comps', label: 'Comps', num: true },
    { key: 'played', label: 'P', num: true },
    { key: 'w', label: 'W', num: true }, { key: 'd', label: 'D', num: true }, { key: 'l', label: 'L', num: true },
    { key: 'gf', label: 'GF', num: true }, { key: 'ga', label: 'GA', num: true },
    { key: 'gd', label: 'GD', num: true, fmt: function (v, r) { return r.played ? signed(r.gf - r.ga, 0) : '—'; } },
    { key: 'ppg', label: 'PPG', num: true, fmt: function (v, r) { return r.played ? '<b>' + num(ppgOf(r), 2) + '</b>' : '—'; } },
    { key: 'wonN', label: 'Trophies', fmt: function (v, r) { return (r.won || []).length ? (r.won || []).map(function (s) { return '<span class="fb-cl-trophy">' + esc(FB.compName(s, true)) + '</span>'; }).join(' ') : ''; } },
    { key: 'partial', label: 'Record', fmt: function (v) { return v ? '<span class="fb-cov partial" data-tip="An archive table without W-D-L is in this season: the sums count the rest">Partial</span>' : '<span class="fb-cov full">Full</span>'; } }
  ], rows.map(function (y) { return FB.merge(y, { gd: y.gf - y.ga, ppg: ppgOf(y), wonN: (y.won || []).length }); }), { caption: 'Year by year' });
}

/* An Argentine club's Tabla Anual place and promedio under its competitions this season (anual.json, relegation.json):
   the two tables that decide its continental places and whether it goes down. */
function drawArgentina(box, C) {
  var slug = 'liga-argentina';
  if (!box || !FB.hasFile(slug, 'anual')) return;
  FB.compFiles(slug, ['anual', 'relegation', 'teams']).then(function (d) {
    if (!FB.alive(box)) return;
    var teams = (d.teams || {}).teams || {};
    var name = (C.doc.names || {})[slug] || Object.keys(teams).filter(function (n) { return String(teams[n].team_id) === String(C.tid); })[0];
    var a = ((d.anual || {}).rows || []).filter(function (r) { return r.team === name; })[0];
    var rel = (d.relegation || {}).rows || [];
    var r = rel.filter(function (x) { return x.team === name; })[0];
    if (!a && !r) return;
    var list = box.querySelector('.fb-cl-now') || (function () { box.innerHTML = '<ul class="fb-cl-now"></ul>'; return box.querySelector('.fb-cl-now'); })();
    var href = FB.href.comp(slug, 'table', { view: 'anual' });
    var li = function (label, href2, fin, rec, tip) {
      return '<li>' + FB.kindChip('league') + '<span class="fb-cl-now-c"><a class="fb-link" href="' + esc(href2) + '">' + esc(label) + '</a></span>' +
        '<span class="fb-cl-now-f">' + fin + '</span><span class="fb-cl-now-rec fb-num"' + (tip ? ' data-tip="' + esc(tip) + '" tabindex="0"' : '') + '>' + rec + '</span></li>';
    };
    var out = '';
    if (a) out += li('Tabla Anual', href, FB.ordinal(a.pos) + ' of ' + ((d.anual || {}).rows || []).length,
      a.pts + ' pts · ' + a.played + ' played · Libertadores ' + pct(a.p_libertadores, a.p_libertadores > 0 && a.p_libertadores < 0.1 ? 1 : 0),
      'Both tournaments\' zone-phase points; it decides the continental places behind the champions and the Copa Argentina winner');
    if (r) out += li('Promedio', FB.href.comp(slug, 'table', { view: 'relegation' }), num(r.promedio_now, 3) + ' · ' + FB.ordinal(rel.length + 1 - r.pos) + ' of ' + rel.length,
      (r.points || 0) + ' pts in ' + (r.matches || 0) + ' · down ' + pct(r.p_any, r.p_any > 0 && r.p_any < 0.1 ? 1 : 0),
      'Points per match over three seasons; the worst promedio goes down beside the last club in the Tabla Anual');
    list.insertAdjacentHTML('beforeend', out);
  });
}

function drawNow(body, C) {
  var rows = C.seasons.filter(function (s) { return s.era === C.cur; }).sort(function (a, b) { return FB.KIND_ORDER[a.kind] - FB.KIND_ORDER[b.kind]; });
  var box = body.querySelector('#cl-now');
  if (!rows.length) { box.innerHTML = FB.empty('Nothing this season', 'No competition row for ' + C.cur + ' yet.'); return; }
  box.innerHTML = '<ul class="fb-cl-now">' + rows.map(function (s0) {
    var s = clean(s0), href = seasonHref(s);
    var rec = has(s.w) ? s.w + '-' + s.d + '-' + s.l + (has(s.gf) ? ' · ' + s.gf + ':' + s.ga : '') : '';
    var str = s.rating && isNum(s.rating.strength_ppg) ? '<span class="fb-cl-now-r" data-tip="Our rating in this competition: expected points a game against an average side there; Elo ' + esc(num(s.rating.elo, 0)) + '">' + num(s.rating.strength_ppg, 2) + '</span>' : '';
    return '<li>' + FB.kindChip(s.kind) + '<span class="fb-cl-now-c">' + (href ? '<a class="fb-link" href="' + esc(href) + '">' + esc(s.cname) + '</a>' : esc(s.cname)) + '</span>' +
      '<span class="fb-cl-now-f">' + esc(finishText(s)) + '</span><span class="fb-cl-now-rec fb-num">' + rec + '</span>' + str + FB.coverageChip(s) + '</li>';
  }).join('') + '</ul>';
}

function drawRatings(body, C) {
  var doc = C.doc;
  var strRows = C.live.filter(function (s) { return s.rating && isNum(s.rating.strength_ppg); });
  var sbox = body.querySelector('#cl-str');
  if (strRows.length) {
    sbox.style.setProperty('--h', Math.max(160, 70 + strRows.length * 34) + 'px');
    QKC.bar(sbox, { horizontal: true, labels: true, labelWidth: 120, fmt: function (v) { return num(v, 2); }, min: 0, valName: 'Expected points per game', catName: 'Competition',
      cats: strRows.map(function (s) { return s.cshort; }), series: [{ name: 'Rating', data: strRows.map(function (s) { return s.rating.strength_ppg; }) }],
      colors: strRows.map(function (s) { return FB.kindColorHex(s.kind); }), hrefs: strRows.map(function (s) { return FB.href.comp(s.comp); }), label: 'Strength by competition' });
  } else { sbox.style.height = 'auto'; sbox.innerHTML = FB.empty('No current rating', 'The model rates clubs in competitions under way.'); }
  var ebox = body.querySelector('#cl-elo');
  var home = doc.home;
  var name = (doc.names || {})[home] || doc.name;
  if (!home || !FB.hasFile(home, 'strength')) { ebox.style.height = 'auto'; ebox.innerHTML = FB.empty('No Elo series', 'Elo is tracked in the followed leagues.'); return; }
  FB.compFile(home, 'strength').then(function (st) {
    if (!FB.alive(ebox)) return;
    var hist = ((st || {}).elo_history || {})[name] || [];
    if (hist.length < 2) { ebox.style.height = 'auto'; ebox.innerHTML = FB.empty('Not enough matches yet', 'The line appears after two league matches.'); return; }
    var all = [];
    Object.keys((st || {}).elo_history || {}).forEach(function (k) { var h = st.elo_history[k]; if (h.length) all.push(h[h.length - 1].elo); });
    var avg = all.length ? all.reduce(function (a, b) { return a + b; }, 0) / all.length : null;
    QKC.line(ebox, { x: hist.map(function (h) { return h.date; }), xFmt: function (v) { return FB.fmtDate(v, { weekday: false }); }, xLabel: function (v) { return FB.fmtDate(v, { year: true }); },
      series: [{ name: 'Elo', data: hist.map(function (h) { return h.elo; }), color: QK.cssVar('--signal'), area: true }], yScale: true,
      ref: isNum(avg) ? { y: Math.round(avg), label: 'league avg' } : undefined, yFmt: function (v) { return num(v, 0); }, endLabels: false, xName: 'Date', yName: 'Elo rating', label: 'Elo through the season' });
  });
}

function drawMost(box, C) {
  var sq = ((C.doc.squad || {}).players || []).slice().sort(function (a, b) { return (b.min || 0) - (a.min || 0); }).slice(0, 8);
  if (!sq.length) { box.innerHTML = ''; return; }
  box.innerHTML = FB.card(C.doc.national ? 'Most used in the latest call-up' : 'Most used this season', 'Minutes across every competition; the full ' + (C.doc.national ? 'call-up' : 'squad') + ' with values and contracts is on the next tab.',
    '<div class="fb-cl-most">' + sq.map(function (x) {
      return '<a class="fb-cl-mp" href="' + esc(FB.href.player(x.id)) + '"><span class="fb-cl-mp-n">' + FB.posBadge(x.pos) + ' ' + esc(x.name) + '</span>' +
        '<span class="fb-cl-mp-s fb-num">' + (x.min || 0) + '\' · ' + (x.g || 0) + 'G ' + (x.a || 0) + 'A' + (isNum(x.rt) && x.rt ? ' · ' + num(x.rt, 2) : '') + '</span></a>';
    }).join('') + '</div>', { foot: '<span></span><a href="' + esc(FB.href.club(C.tid, { tab: 'squad' })) + '">' + (C.doc.national ? 'Full call-up →' : 'Full squad →') + '</a>' });
}

/* ── the competition dossier (?c=<live competition>) */
function headline(c, prob, bands) {
  if (!prob) return [];
  var k = c.kind;
  if (k === 'liga') return [['Champion', prob.p_title], ['Top 8', prob.p_top8], ['Libertadores', prob.p_libertadores], ['Relegation', prob.p_relegation]];
  if (k === 'conference') return [['MLS Cup', prob.p_cup], ['Playoffs', prob.p_playoffs], ['Shield', prob.p_title]];
  if (k === 'playoff') return [['Champion', prob.p_cup], ['Liguilla', prob.p_playoffs]];
  if (k === 'cup') return [['Win it', prob.p_cup], ['Reach the final', prob.p_conference]];
  var up = (bands || []).filter(function (b) { return b.kind === 'up'; })[0];
  var downs = (bands || []).filter(function (b) { return b.kind === 'down'; });
  var out = [['Title', prob.p_title]];
  if (up) out.push([up.label, (prob.bands || {})[up.key]]);
  if (downs.length) out.push(['Relegation', downs.reduce(function (s, b) { return s + ((prob.bands || {})[b.key] || 0); }, 0)]);
  return out;
}
function drawDossier(box, C, slug) {
  var c = FB.comp(slug);
  box.innerHTML = FB.card('In ' + esc(c.name) + ' ' + esc(FB.currentSeason(c).season), 'Our chances, the season profile and the players in this competition. <a href="' + esc(FB.href.comp(slug)) + '">' + esc(c.short_name || c.name) + ' →</a>', FB.loading('lines', 4), { bodyId: 'cl-dos-b' });
  FB.compFiles(slug, ['teams', 'probs', 'table', 'strength', 'team_stats', 'players_live']).then(function (d) {
    var b = box.querySelector('#cl-dos-b');
    if (!FB.alive(b)) return;
    var teams = (d.teams || {}).teams || {};
    var name = (C.doc.names || {})[slug] || Object.keys(teams).filter(function (n) { return String(teams[n].team_id) === C.tid; })[0] || C.doc.name;
    var prob = ((d.probs || {}).teams || []).filter(function (t) { return t.team === name; })[0] || null;
    var str = ((d.strength || {}).rows || []).filter(function (r) { return r.team === name; })[0] || {};
    var t = d.table || {};
    var row = (t.standings || t.overall || []).filter(function (r) { return r.team === name; })[0];
    if (!row && t.conferences) Object.keys(t.conferences).forEach(function (g) { row = row || (t.conferences[g] || []).filter(function (r) { return r.team === name; })[0]; });
    var ts = ((d.team_stats || {}).teams || {})[name] || { season: {}, matches: [] };
    var season = ts.season || {};
    var tiles = headline(c, prob, (d.probs || {}).bands).filter(function (h) { return isNum(h[1]); }).map(function (h, i) { return FB.kpi(h[0], pct(h[1], h[1] < 0.1 && h[1] > 0 ? 1 : 0), { signal: i === 0, sub: 'our chance' }); });
    if (row) tiles.unshift(FB.kpi(c.kind === 'liga' ? 'Tabla Anual' : 'Table', FB.ordinal(row.pos), { sub: row.pts + ' pts · ' + row.w + '-' + row.d + '-' + row.l }));
    if (isNum(str.strength_ppg)) tiles.push(FB.kpi('Rating', num(str.strength_ppg, 2), { sub: 'Elo ' + num(str.elo, 0) + (str.strength_rank ? ' · rank ' + str.strength_rank : '') }));
    if (isNum(season.xg)) tiles.push(FB.kpi('xG for / against', num(season.xg, 2) + ' / ' + num(season.xga, 2), { sub: 'a match' }));
    if (isNum(str.luck)) tiles.push(FB.kpi('Luck', signed(str.luck, 1), { sub: 'points above the xG', tip: 'Actual points minus the points the xG deserved' }));
    var metrics = ((d.team_stats || {}).metrics || []).filter(function (m) { return isNum(season[m.key]) && isNum((season.pct || {})[m.key]); }).slice(0, 14);
    var players = ((d.players_live || {}).players || []).filter(function (p) { return p.team === name; }).sort(function (a, b) { return (b.minutes || 0) - (a.minutes || 0); });
    b.innerHTML = (tiles.length ? FB.kpis(tiles) : '') + (str.form_results ? '<p class="fb-cap">Form ' + FB.formChips(str.form_results) + '</p>' : '') +
      FB.grid(
        FB.card('Season profile', 'Percentile within ' + esc(c.short_name || c.name) + ', from the team-stat sheets.', metrics.length ? QK.pctlBars(metrics.map(function (m) { return { label: m.label, pctl: season.pct[m.key], value: FB.fmtMetric(season[m.key], m.fmt) }; })) : FB.muted('No team-stat sheets yet.'), { span: 5 }) +
        FB.card('xG by match', 'For and against, oldest to newest.', FB.chartBox('cl-dos-xg', 300, 'xG for and against by match'), { span: 7 }), 'fb-mt') +
      '<div class="fb-mt">' + FB.card('Players in ' + esc(c.name), players.length + ' players this season; percentile chips against positional peers in the competition.', '<div id="cl-dos-p"></div>', { flush: true }) + '</div>';
    var ms = (ts.matches || []).slice().reverse().filter(function (m) { return isNum(m.xg); });
    var xbox = b.querySelector('#cl-dos-xg');
    if (ms.length) QKC.bar(xbox, { legend: true, fmt: function (v) { return num(v, 2); }, valName: 'Expected goals (xG)', catName: 'Match', cats: ms.map(function (m) { return (m.ha === 'H' ? 'v ' : '@ ') + m.opp + ' ' + m.gf + '-' + m.ga; }),
      series: [{ name: 'xG for', data: ms.map(function (m) { return m.xg; }), color: QK.cssVar('--c-1') }, { name: 'xG against', data: ms.map(function (m) { return isNum(m.xga) ? m.xga : null; }), color: QK.cssVar('--c-2') }], label: 'xG by match' });
    else { xbox.style.height = 'auto'; xbox.innerHTML = FB.empty('No xG yet'); }
    var pc = function (key, fmt) { return { key: key, label: '', num: true, fmt: function (v, r) { return FB.fmtMetric(v, fmt); }, pctl: '_p_' + key }; };
    var rowsP = players.map(function (p) { var o = FB.merge(p, {}); Object.keys(p.pct || {}).forEach(function (k) { o['_p_' + k] = p.pct[k]; }); return o; });
    var cols = [
      { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return FB.playerLink(r.player_id, v) + ' ' + FB.posBadge(r.position || (r.is_gk ? 'G' : '')) + (r.current === false ? ' ' + FB.badge('left', '', 'No longer at the club; minutes played here still count') : ''); } },
      { key: 'age', label: 'Age', num: true }, { key: 'matches', label: 'Apps', num: true }, { key: 'minutes', label: 'Min', num: true },
      { key: 'goals', label: 'G', num: true }, { key: 'assists', label: 'A', num: true },
      { key: 'xg', label: 'xG', num: true, d: 2 }, { key: 'xa', label: 'xA', num: true, d: 2 }
    ];
    var c1 = pc('npxg_90', '2'); c1.label = 'npxG/90'; var c2 = pc('xa_90', '2'); c2.label = 'xA/90'; var c3 = pc('pass_pct', 'pct'); c3.label = 'Pass %'; var c4 = pc('rating', '2'); c4.label = 'Rating';
    cols = cols.concat([c1, c2, c3, c4]);
    if (rowsP.length) FB.table(b.querySelector('#cl-dos-p'), cols, rowsP, { maxHeight: 520, caption: 'Players in the competition' });
    else b.querySelector('#cl-dos-p').innerHTML = FB.muted('No player lines yet.');
  });
}

/* ── season by season */
function drawSeasons(body, C, q) {
  var ss = C.seasons.filter(keepFn(q)).map(clean);
  if (!ss.length) { body.innerHTML = FB.empty('No season matches the filter', 'Clear the filter to see every season.'); return; }
  var eras = Array.from(new Set(ss.map(function (s) { return s.era; }))).sort(function (a, b) { return FB.eraKey(b) - FB.eraKey(a); });
  var years = {};
  (C.doc.years || []).forEach(function (y) { years[y.era] = y; });
  var done = C.matches.filter(keepFn(q)).filter(function (m) { return m.status === 'finished' && isNum(m.gf); });
  body.innerHTML = FB.card('Points per game by season', 'Matches in the stores, one bar per competition.', FB.chartBox('cl-ppg', 280, 'Points per game by season and competition')) +
    eras.map(function (e) {
      var y = years[e];
      var tot = y && !q.c ? '<span class="fb-cl-tot fb-num">' + y.played + ' played · ' + y.w + '-' + y.d + '-' + y.l + ' · ' + y.gf + ':' + y.ga + (y.played ? ' · ' + num(ppgOf(y), 2) + ' PPG' : '') + '</span>' : '';
      var won = y && (y.won || []).length ? (y.won || []).map(function (s) { return '<span class="fb-cl-trophy">' + esc(FB.compName(s, true)) + '</span>'; }).join(' ') : '';
      return '<section class="fb-sec"><div class="fb-cl-era"><h2>' + esc(e) + (e === C.cur ? ' ' + QK.tag('this season', 'signal') : '') + '</h2>' + tot + won + '</div>' +
        '<div class="qk-card"><div class="qk-card-body flush" data-era="' + esc(e) + '"></div></div></section>';
    }).join('');
  Array.prototype.forEach.call(body.querySelectorAll('[data-era]'), function (n) {
    var e = n.getAttribute('data-era');
    var rows = ss.filter(function (s) { return s.era === e; }).sort(function (a, b) { return FB.KIND_ORDER[a.kind] - FB.KIND_ORDER[b.kind] || String(a.cname).localeCompare(String(b.cname)); });
    FB.table(n, [
      { key: 'cname', label: 'Competition', sticky: true, fmt: function (v, r) { var hr = seasonHref(r); return (hr ? '<a class="fb-link" href="' + esc(hr) + '">' + esc(v) + '</a>' : esc(v)) + ' <span class="qk-muted fb-num">' + esc(r.season || '') + '</span>'; } },
      { key: 'kind', label: 'Kind', fmt: function (v) { return FB.kindChip(v); } },
      { key: 'pos', label: 'Finish', fmt: function (v, r) { return r.stage === 'winner' ? '<b class="fb-cl-win">' + esc(finishText(r)) + '</b>' : esc(finishText(r)); } },
      { key: 'played', label: 'P', num: true }, { key: 'w', label: 'W', num: true }, { key: 'd', label: 'D', num: true }, { key: 'l', label: 'L', num: true },
      { key: 'gf', label: 'GF', num: true }, { key: 'ga', label: 'GA', num: true },
      { key: 'pts', label: 'Pts', num: true, fmt: function (v, r) { return isNum(v) && r.comp !== 'friendlies' && (r.kind === 'league' || (isNum(r.w) && v === 3 * r.w + r.d)) ? '<b>' + v + '</b>' : '—'; } },
      { key: 'rt', label: 'Rating', num: true, sort: false, fmt: function (v, r) { return r.rating ? '<span data-tip="Our attack / defence ratings from the fit (log goal rates; lower defence is better)">' + signed(r.rating.attack, 2) + ' / ' + signed(r.rating.defence, 2) + '</span>' : '—'; } },
      { key: 'coverage', label: 'Player data', sort: false, fmt: function (v, r) { return FB.coverageChip(r, { full: !!v }) || (r.source === 'archive' ? '<span class="qk-muted">archive</span>' : ''); } }
    ], rows, { caption: 'Season ' + e });
  });
  var asc = eras.slice().reverse();
  var compsIn = Array.from(new Set(done.map(function (m) { return m.comp; })));
  var pbox = body.querySelector('#cl-ppg');
  if (asc.length && compsIn.length) {
    QKC.bar(pbox, { legend: true, max: 3, valName: 'Points per game', catName: 'Season', fmt: function (v) { return num(v, 2); }, cats: asc,
      series: compsIn.map(function (s) {
        return { name: FB.compName(s, true), color: FB.kindColorHex(FB.kindOf(s)), data: asc.map(function (e) {
          var g = done.filter(function (m) { return m.comp === s && m.era === e; });
          return g.length ? Math.round(g.reduce(function (t, m) { return t + (m.gf > m.ga ? 3 : m.gf === m.ga ? 1 : 0); }, 0) / g.length * 100) / 100 : null;
        }) };
      }), label: 'Points per game by season and competition' });
  } else { pbox.style.height = 'auto'; pbox.innerHTML = FB.empty('No finished match in the filter'); }
}

/* ── squad */
function drawSquad(body, C, q) {
  var doc = C.doc, sq = (doc.squad || {}).players || [], src = (doc.squad || {}).source;
  var MV = null;      // {movement, rows: {pid: moves.json row}, meta} once loaded (followed leagues only)
  if (!sq.length) { body.innerHTML = FB.empty('No squad on record yet', 'The squad list is fetched on a rotation.'); return; }
  var mv = sq.filter(function (x) { return isNum(x.mv); });
  var tot = FB.sum(mv, 'mv');
  var ages = sq.map(function (x) { return x.age; }).filter(isNum);
  var soon = sq.filter(function (x) { var d = FB.parseDate(x.until); return d && d - Date.now() < 365 * 864e5; }).length;
  var top = mv.slice().sort(function (a, b) { return b.mv - a.mv; })[0];
  body.innerHTML = FB.kpis([
    FB.kpi(doc.national ? 'Called up' : 'Squad', String(sq.length), { sub: src === 'roster' ? 'Sofascore\'s current squad list' : doc.national ? 'played in the latest international window' : 'from appearances' }),
    FB.kpi('Squad value', mv.length ? FB.money(tot) : '—', { sub: mv.length + ' of ' + sq.length + ' valued (Sofascore, reference)' }),
    FB.kpi('Most valuable', top ? esc(top.name) : '—', { text: true, sub: top ? FB.money(top.mv) : '' }),
    FB.kpi('Average age', ages.length ? num(ages.reduce(function (a, b) { return a + b; }, 0) / ages.length, 1) : '—', { sub: ages.length ? 'youngest ' + Math.min.apply(null, ages) + ' · oldest ' + Math.max.apply(null, ages) : '' }),
    FB.kpi('Contracts ending', doc.national ? '—' : String(soon), { sub: doc.national ? '' : 'within twelve months' })
  ]) +
    '<section class="fb-sec">' + FB.grid(
      FB.card('Age and value', 'Each player: age across, ' + (mv.length ? 'market value' : 'minutes') + ' up; marker size by minutes this season; colour by position.', FB.chartBox('cl-sq-sc', 340, 'Squad by age and value'), { span: 7 }) +
      FB.card(doc.national ? 'By position' : 'Contracts by year of expiry', doc.national ? 'Players by position in the call-up.' : 'Players whose contract ends in each year (Sofascore).', FB.chartBox('cl-sq-ct', 340, 'Contracts by year'), { span: 5 })
    ) + '</section>' +
    '<section class="fb-sec">' + FB.card(doc.national ? 'Latest call-up' : 'Current squad', ((doc.squad || {}).as_of ? 'As of ' + esc(FB.fmtDate(doc.squad.as_of, true)) + '. ' : '') + 'This season\'s appearances across every competition (' + esc((doc.squad || {}).era || C.cur) + ').' +
      (doc.national ? ' Club from the people registry.' : ''), '<div id="cl-sq-key"></div><div id="cl-sq-t"></div>') + '</section>';
  // tables by position (people index for national team / club cross-links)
  var PEOPLE = null;
  var draw = function (people) {
    if (people) PEOPLE = people; else people = PEOPLE;
    var host = body.querySelector('#cl-sq-t');
    if (!FB.alive(host)) return;
    host.innerHTML = POS_ORDER.concat(['?']).map(function (pos) {
      var g = sq.filter(function (x) { return pos === '?' ? POS_ORDER.indexOf(x.pos) < 0 : x.pos === pos; });
      return g.length ? '<div class="fb-cl-pos"><h3>' + esc(FB.POS_GROUP[pos] || 'Position not recorded') + ' <span class="qk-muted fb-num">' + g.length + '</span></h3><div data-pos="' + esc(pos) + '"></div></div>' : '';
    }).join('');
    Array.prototype.forEach.call(host.querySelectorAll('[data-pos]'), function (n) {
      var pos = n.getAttribute('data-pos');
      var g = sq.filter(function (x) { return pos === '?' ? POS_ORDER.indexOf(x.pos) < 0 : x.pos === pos; }).map(function (x) { return FB.merge(x, { shirtN: Number(x.shirt) || 999, ix: people ? people[String(x.id)] || {} : {} }); });
      var cols = [
        { key: 'shirtN', label: '#', num: true, fmt: function (v, r) { return r.shirt && !doc.national ? esc(r.shirt) : ''; } },
        { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return FB.playerLink(r.id, v) + (src !== 'roster' && !doc.national && !r.apps ? ' <span class="qk-muted" data-tip="Listed from the latest club appearance; no appearance this season">not played</span>' : ''); } },
        { key: 'age', label: 'Age', num: true },
        { key: 'nat', label: 'Nat' },
        { key: 'link', label: doc.national ? 'Club' : 'International', sort: false, fmt: function (v, r) {
          var ix = r.ix || {};
          if (doc.national) return ix.club_tid ? FB.clubLink(ix.club_tid, ix.club) : esc(ix.club || '');
          return ix.nt_tid ? FB.clubLink(ix.nt_tid, ix.nt) : '';
        } },
        { key: 'apps', label: 'Apps', num: true }, { key: 'min', label: 'Min', num: true },
        { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true },
        { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return isNum(v) && v ? num(v, 2) : '—'; } },
        { key: 'mv', label: 'Value', num: true, fmt: function (v, r) { return isNum(v) ? FB.money(v, r.mvc) : '—'; }, tip: 'Sofascore market value, reference only' },
        { key: 'until', label: 'Contract', num: true, fmt: function (v) { return v ? esc(String(v).slice(0, 7)) : '—'; }, tip: 'Contract end, Sofascore' }
      ];
      if (MV && FB.moves) {
        g.forEach(function (x) { var r = MV.rows[String(x.id)] || MV.rows[FB.personId(x.id)]; x.mvP = r ? r.p : null; x.mvRow = r || null; });
        cols.push({ key: 'mvP', label: 'Chance of moving', num: true, tip: 'Our chance the player leaves the club in ' + (MV.movement.horizon || 'the coming window') + ': a base rate (how often similar players left in the last window of the same kind), split by type of move. A dash: not enough recent minutes for an estimate.',
          fmt: function (v, r) { return FB.moves.cell(r.mvRow, MV.meta); } });
      }
      board(n, cols, g, { sort: { key: doc.national ? 'min' : 'shirtN', dir: doc.national ? 'desc' : 'asc' }, caption: (FB.POS_GROUP[pos] || 'Players') });
    });
  };
  draw(null);
  FB.peopleIndex().then(function (pi) { if (FB.alive(body)) draw(pi.byId); });
  /* who moves next: the club's movement block (value/club/<tid>.json), then moves.json for the type split; nothing is
     drawn when the payload has no movement for the club */
  if (C.valueLeague && FB.moves) FB.load('value/club/' + C.tid + '.json').then(function (d) {
    var mv = d && d.movement;
    if (!mv || !FB.alive(body)) return null;
    return FB.moves.load().then(function (M) {
      if (!M || !FB.alive(body)) return;
      MV = { movement: mv, rows: M.byId, meta: M.meta };
      var host = body.querySelector('#cl-sq-key');
      if (host) host.innerHTML = FB.moves.keyHTML(M.meta, mv);
      draw(null);
    });
  });
  // charts
  var useMv = mv.length >= 3;
  var pts = sq.filter(function (x) { return isNum(x.age) && (useMv ? isNum(x.mv) : true); }).map(function (x) {
    return { x: x.age, y: useMv ? x.mv / 1e6 : (x.min || 0), name: x.name + ' · ' + (FB.POS_LABEL[x.pos] || '') + (isNum(x.mv) ? ' · ' + FB.money(x.mv) : ''), size: 8 + Math.sqrt(x.min || 0) / 3, color: posSlotHex(x.pos), href: FB.href.player(x.id), label: FB.surname(x.name) };
  });
  var scb = body.querySelector('#cl-sq-sc');
  if (pts.length) QKC.scatter(scb, { points: pts, xName: 'Age', yName: useMv ? 'Value (€m)' : 'Minutes', labelTop: 8, xFmt: function (v) { return num(v, 0); }, yFmt: function (v) { return useMv ? '€' + num(v, 0) + 'm' : num(v, 0); }, label: 'Squad by age and value' });
  else { scb.style.height = 'auto'; scb.innerHTML = FB.empty('No ages on record'); }
  var ctb = body.querySelector('#cl-sq-ct');
  if (doc.national) {
    QKC.bar(ctb, { labels: true, fmt: function (v) { return num(v, 0); }, cats: POS_ORDER.map(function (p) { return FB.POS_GROUP[p]; }),
      series: [{ name: 'Players', data: POS_ORDER.map(function (p) { return sq.filter(function (x) { return x.pos === p; }).length; }) }], colors: POS_ORDER.map(posSlotHex), valName: 'Players', label: 'Players by position' });
  } else {
    var by = {};
    sq.forEach(function (x) { var y = x.until ? String(x.until).slice(0, 4) : null; if (y) by[y] = (by[y] || 0) + 1; });
    var ys = Object.keys(by).sort();
    if (ys.length) QKC.bar(ctb, { labels: true, colors: ys.map(function () { return QK.cssVar('--c-1'); }), fmt: function (v) { return num(v, 0); }, cats: ys, series: [{ name: 'Contracts ending', data: ys.map(function (y) { return by[y]; }) }], valName: 'Contracts ending', catName: 'Year of expiry', label: 'Contracts by year of expiry' });
    else { ctb.style.height = 'auto'; ctb.innerHTML = FB.empty('No contract dates on record'); }
  }
}

/* ── matches */
function drawMatches(body, C, q) {
  var ms = C.matches.filter(keepFn(q));
  var up = ms.filter(function (m) { return m.status === 'scheduled' || m.status === 'live'; }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
  var done = ms.filter(function (m) { return m.status !== 'scheduled' && m.status !== 'live'; });
  body.innerHTML = recordTiles(ms) + '<section class="fb-sec">' + FB.grid(
    FB.card('xG difference by match', 'Oldest to newest; colour by competition kind. Above zero: the club created more than it allowed.', FB.chartBox('cl-xgd', 260, 'xG difference by match'), { span: 7 }) +
    FB.card('Coming up', up.length + ' fixtures in the filter; the bar is our home / draw / away chance.', '<div class="fb-fxlist">' + (up.length ? up.slice(0, 8).map(function (m) { return FB.fixtureRow(asFixture(C, m), { date: true, comp: true }); }).join('') : FB.empty('No fixtures', 'Nothing scheduled in the filter.')) + '</div>' +
      (up.length > 8 ? '<p class="fb-cap">' + (up.length - 8) + ' more later; each competition\'s fixtures are on its page.</p>' : ''), { span: 5 })
  ) + '</section>' +
    '<section class="fb-sec">' + FB.card('Results', done.length + ' matches, newest first. The score links to the match centre where there is one.', '<div id="cl-res"></div>', { flush: true }) + '</section>';
  FB.table(body.querySelector('#cl-res'), [
    { key: 'date', label: 'Date', fmt: function (v) { return '<span class="fb-num">' + esc(FB.fmtDate(v, true)) + '</span>'; } },
    { key: 'comp', label: 'Competition', fmt: function (v, r) { return FB.compLink(v, { short: true }) + (r.round ? ' <span class="qk-muted">' + esc(FB.roundText(r, v, true)) + '</span>' : ''); } },
    { key: 'opp', label: 'Opponent', sticky: true, fmt: function (v, r) { return FB.clubLink(r.opp_tid, v); } },
    { key: 'home', label: 'H/A', fmt: function (v) { return v ? 'H' : 'A'; } },
    { key: 'gd', label: 'Result', num: true, fmt: function (v, r) {
      if (r.status !== 'finished') return '<span class="qk-muted">' + esc(r.status) + '</span>';
      var t = (r.res ? String(r.res) : resCls(r.gf, r.ga) + ' ' + r.gf + '-' + r.ga);
      var k = t.charAt(0);
      var s = '<span class="fb-cl-res r-' + esc(k) + '">' + esc(t) + '</span>';
      return r.detail ? '<a href="' + esc(FB.href.match(r.comp, r.id)) + '" title="Match centre">' + s + '</a>' : s;
    } },
    { key: 'xgd', label: 'xG', num: true, fmt: function (v, r) { return r.xg && isNum(r.xg[0]) ? num(r.xg[0], 2) + '–' + num(r.xg[1], 2) : '—'; } }
  ], done.map(function (m) { return FB.merge(m, { gd: isNum(m.gf) ? m.gf - m.ga : null, xgd: m.xg && isNum(m.xg[0]) ? m.xg[0] - m.xg[1] : null }); }), { maxHeight: 640, caption: 'Results' });
  var xs = done.filter(function (m) { return m.xg && isNum(m.xg[0]) && m.status === 'finished'; }).slice(0, 80).reverse();
  var xb = body.querySelector('#cl-xgd');
  if (xs.length >= 2) {
    QKC.mount(xb, function (T) {
      return {
        grid: { left: 8, right: 8, top: 26, bottom: 28, containLabel: true },
        xAxis: QKC.axis(T, { type: 'category', data: xs.map(function (m, i) { return i + 1; }), split: false, line: true, name: 'Match, oldest first', nameLocation: 'middle', nameGap: 26 }),
        yAxis: QKC.axis(T, { fmt: function (v) { return signed(v, 1); }, name: 'xG difference', nameAlign: 'left' }),
        tooltip: QKC.tooltip(T, { formatter: function (p) { var m = xs[p.dataIndex]; return '<div style="font-weight:600">' + esc(FB.fmtDate(m.date, true)) + ' · ' + esc(FB.compName(m.comp, true)) + '</div>' + esc((m.home ? 'v ' : '@ ') + m.opp + ' ' + m.gf + '-' + m.ga) + QKC.tipRow(p.color, 'xG difference', signed(m.xg[0] - m.xg[1], 2)); } }),
        series: [{ type: 'bar', barMaxWidth: 14, data: xs.map(function (m) { return { value: Math.round((m.xg[0] - m.xg[1]) * 100) / 100, href: m.detail ? FB.href.match(m.comp, m.id) : undefined, itemStyle: { color: FB.kindColorHex(m.kind) } }; }) }]
      };
    }, { label: 'xG difference by match' });
  } else { xb.style.height = 'auto'; xb.innerHTML = FB.empty('Not enough matches with xG in the filter'); }
}

/* ── top performers (overview): the club's best players in its home league by our value model (GAR/90), overall
   and at each position (METRICS_SPEC peer groups: CB, FB/WB, DM/CM, AM/W, ST, GK), each against the league's
   qualified players at that position (the group minimum or the league's minutes floor, whichever is higher):
   the league percentile (mid-rank, as every other card) and the rank. From the league's players_live.json. */
var PERF_GROUPS = ['gk', 'cb', 'fb', 'dm_cm', 'am_w', 'st'];
function perfRow(r) {
  var p = r.pct;
  return '<div class="fb-cl-pr"><span class="who">' + FB.playerLink(r.id, r.name) + '<small>' + esc(r.role) + ' · ' + FB.int(r.min) + '\'</small></span>' +
    '<span class="v fb-num">' + signed(r.gar, 2) + '</span>' +
    '<span class="m">' + QK.meter(p, { label: r.name + ': ' + QK.ordinal(p) + ' percentile among ' + r.peer }) +
    '<span class="qk-pbox num" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '">' + p + '</span>' +
    '<span class="rk">' + FB.ordinal(r.rank) + ' of ' + r.n + ' ' + esc(r.peer) + (r.allRank ? ' · ' + FB.ordinal(r.allRank) + ' of ' + r.allN + ' overall' : '') + '</span></span></div>';
}
function drawPerformers(box, C) {
  var slug = C.doc.home;
  if (!box || !slug || !FB.comp(slug) || C.doc.national) { if (box) box.innerHTML = ''; return; }
  FB.compFiles(slug, ['players_live', 'teams']).then(function (d) {
    if (!FB.alive(box)) return;
    var pl = d.players_live || {}, rows = pl.players || [];
    var teams = (d.teams || {}).teams || {};
    var name = Object.keys(teams).filter(function (t) { return String(teams[t].team_id) === String(C.tid); })[0] || C.doc.name;
    var floor = pl.minutes_floor;
    var all = rows.filter(function (r) { var g = FB.peerGroup(r.role); return g && isNum(r.gar90) && (r.minutes || 0) >= FB.peerMin(g, floor); });
    var byG = {};
    all.forEach(function (r) { var g = FB.peerGroup(r.role); (byG[g.id] = byG[g.id] || []).push(r); });
    var allSorted = all.map(function (r) { return r.gar90; }).sort(function (a, b) { return b - a; });
    var line = function (r) {
      var g = FB.peerGroup(r.role), peers = byG[g.id], n = peers.length;
      var below = peers.filter(function (x) { return x.gar90 < r.gar90; }).length, ties = peers.filter(function (x) { return x.gar90 === r.gar90; }).length;
      var pctl = n > 1 ? Math.round(100 * (below + 0.5 * (ties - 1)) / (n - 1)) : 50;
      return { id: r.player_id, name: r.name, role: r.role, min: r.minutes, gar: r.gar90, pct: pctl, n: n, peer: g.short, g: g,
        rank: 1 + peers.filter(function (x) { return x.gar90 > r.gar90; }).length,
        allRank: 1 + allSorted.filter(function (v) { return v > r.gar90; }).length, allN: allSorted.length };
    };
    var mine = all.filter(function (r) { return r.team === name; }).map(line).sort(function (a, b) { return b.gar - a.gar; });
    var comp = FB.comp(slug), where = esc(comp.short_name || comp.name);
    var head = FB.secHead('Top performers', 'The club\'s best players in ' + esc(comp.name) + ' this season by our value model, overall and at each position, against the league\'s qualified players at the same position.', '', 'Against the league');
    if (!mine.length) { box.innerHTML = head + FB.card('Top performers', null, FB.muted('No player has reached the minutes where the numbers settle yet (' + (isNum(floor) ? FB.int(Math.max(450, floor)) : '450') + '+ minutes in ' + where + ').')); return; }
    var groups = PERF_GROUPS.map(function (id) { var rs = mine.filter(function (r) { return r.g.id === id; }).slice(0, 2); return rs.length ? '<div class="fb-cl-tpg"><h5>' + esc(rs[0].g.name.charAt(0).toUpperCase() + rs[0].g.name.slice(1)) + '</h5>' + rs.map(perfRow).join('') + '</div>' : ''; }).join('');
    var tag = QK.ours ? ' ' + QK.ours({ model: 'GAR, goals above replacement per 90', about: 'the player value model on the Model page' }) : '';
    box.innerHTML = head + FB.grid(
      FB.card('Best overall' + tag, 'GAR/90: goals of expected goal difference added per 90 over a replacement-level player in the same role. The box is the percentile among ' + where + '\'s qualified players at the same position.', '<div class="fb-cl-tp fb-cl-tp1">' + mine.slice(0, 6).map(perfRow).join('') + '</div>', { span: 12 }) +
      FB.card('By position' + tag, 'The best two at each position, each against the league at that position.', '<div class="fb-cl-tp">' + groups + '</div>', { span: 12 })
    ) + '<p class="fb-cap">Qualified: at least ' + FB.int(Math.max(450, isNum(floor) ? floor : 0)) + ' league minutes (goalkeepers ' + FB.int(Math.max(900, isNum(floor) ? floor : 0)) + '), the metric spec\'s minimum or the league\'s floor, whichever is higher. <a href="' + esc(FB.href.comp(slug, 'players')) + '">Every player in ' + where + ' →</a></p>';
  });
}

/* ── strengths, needs, budget and ledger (value/club/<tid>.json) */
function drawNeedsMini(box, C, d) {
  if (!box) return;
  if (!d || !d.units) { box.innerHTML = ''; return; }
  var units = d.units;
  box.innerHTML = FB.grid(
    FB.card('Strengths and needs', 'Each unit graded against ' + esc(FB.compName(d.league)) + '\'s clubs on the projected value of the players used this season (percentile).', FB.chartBox('cl-units', 240, 'Unit percentiles'), { span: 7 }) +
    FB.card('Where to strengthen', '', '<ol class="fb-cl-list">' + (d.weaknesses || []).map(function (k) {
      var u = units.filter(function (x) { return x.unit === k; })[0] || {};
      return '<li><b>' + esc(u.label || k) + '</b> ' + grade(u.grade) + '</li>';
    }).join('') + '</ol>' + (d.budget && d.budget.summer ? '<p class="fb-cap">Summer budget model: <b>' + FB.money(d.budget.summer.mid) + '</b> (25-75%: ' + moneyRange(d.budget.summer.lo, d.budget.summer.hi) + ').</p>' : ''),
      { span: 5, foot: '<span></span><a href="' + esc(FB.href.club(C.tid, { tab: 'transfers' })) + '">Needs and transfers →</a>' })
  );
  unitChart(box.querySelector('#cl-units'), units);
}
function unitChart(el, units) {
  QKC.bar(el, { horizontal: true, labels: true, labelWidth: 170, max: 100, min: 0, fmt: function (v) { return num(v, 0); }, valName: 'Percentile in the league',
    cats: units.map(function (u) { return u.label + ' · ' + (u.grade || ''); }), series: [{ name: 'Percentile in the league', data: units.map(function (u) { return u.pct; }) }],
    colors: units.map(function (u) { return u.pct >= 50 ? QK.cssVar('--div-pos') : QK.cssVar('--div-neg'); }), label: 'Unit percentiles in the league' });
}
function drawTransfers(body, C) {
  body.innerHTML = FB.loading('lines', 6);
  return FB.load('value/club/' + C.tid + '.json').then(function (d) {
    if (!FB.alive(body)) return;
    if (!d || !d.units) { body.innerHTML = FB.empty('No value file', 'Strengths, needs and budgets are built for clubs of the followed leagues.'); return; }
    var units = {};
    d.units.forEach(function (u) { units[u.unit] = u; });
    var evidence = function (u) {
      if (!u) return '';
      var e = u.evidence || {};
      return '<b>' + esc(u.label) + '</b>: ' + signed(u.rate, 2) + ' GAR/90 from the players used, ' + FB.ordinal(u.rank) + ' of ' + u.n + ' in ' + esc(FB.compName(d.league)) +
        (e.component && isNum(e.delta) && Math.abs(e.delta) >= 0.005 ? '; ' + esc(e.component) + ' ' + signed(e.delta, 2) + ' a player per 90 against the league\'s ' + esc(String(u.label).toLowerCase()) : '') +
        (u.few ? ' (few minutes this season: graded on the squad\'s best at the position)' : '') + (u.empty ? ' (no current player has played here)' : '') + '.';
    };
    var win = d.window;
    var allAbove = (d.weaknesses || []).every(function (k) { return units[k] && units[k].pct >= 50; });
    var allBelow = (d.strengths || []).every(function (k) { return units[k] && units[k].pct < 50; });
    body.innerHTML = (d.movement && FB.moves ? '<section id="cl-moves"></section>' : '') + FB.secHead('Strengths and needs', 'Each unit graded against ' + esc(FB.compName(d.league)) + '\'s clubs on the projected value of the players used this season.', '', 'Value') + FB.grid(
      FB.card('Unit grades', esc(FB.compName(d.league)) + ' · as of ' + esc(d.as_of || '') + ' · percentile among the league\'s clubs.', FB.chartBox('cl-tu', 260, 'Unit percentiles'), { span: 5 }) +
      FB.card('Units', 'Graded on the projected value (goals above replacement per 90) of the current players used there this season.', '<div id="cl-tut"></div>', { span: 7, flush: true }) +
      FB.card('Top strengths' + (allBelow ? ' (relative)' : ''), allBelow ? 'Every unit is below the league median; these are the best of them.' : '', '<ol class="fb-cl-list">' + (d.strengths || []).map(function (k) { return '<li>' + evidence(units[k]) + '</li>'; }).join('') + '</ol>', { span: 6 }) +
      FB.card('Top weaknesses' + (allAbove ? ' (relative)' : ''), allAbove ? 'Even these are above the league median.' : '', '<ol class="fb-cl-list">' + (d.weaknesses || []).map(function (k) { return '<li>' + evidence(units[k]) + '</li>'; }).join('') + '</ol>', { span: 6 })
    ) +
      '<section class="fb-sec" id="cl-budget"></section>' +
      '<p class="fb-cap">Grades from on-field value; budgets from our budget model. <a href="#/value?club=' + esc(d.tid) + '">The squad on the value table →</a> · <a href="#/value/simulator?to=' + esc(d.tid) + '">Transfer simulator →</a> · <a href="#/value/transfers?q=' + enc(d.name || '') + '">Its transfers →</a></p>';
    unitChart(body.querySelector('#cl-tu'), d.units);
    if (d.movement && FB.moves) FB.moves.clubViews(body.querySelector('#cl-moves'), d);
    board(body.querySelector('#cl-tut'), [
      { key: 'label', label: 'Unit', sticky: true },
      { key: 'pct', label: 'Grade', fmt: function (v, r) { return grade(r.grade); } },
      { key: 'rate', label: 'GAR/90', type: 'pctl', pctl: 'pct', fmt: function (v) { return signed(v, 2); }, tip: 'Goals above replacement per 90 of the players used; the cell colour is the unit\'s percentile among the league\'s clubs' },
      { key: 'rank', label: 'Rank', num: true, fmt: function (v, r) { return v + '/' + r.n; } },
      { key: 'depthTxt', label: 'Players (minutes)', sort: false, fmt: function (v, r) { return (r.depth || []).filter(function (x) { return x.min > 0; }).slice(0, 3).map(function (x) { return FB.playerLink(x.id, x.name) + ' <span class="qk-muted fb-num">' + x.min + '\'</span>'; }).join(', ') || '—'; } }
    ], d.units, { caption: 'Units' });
    drawBudget(body.querySelector('#cl-budget'), d);
  });
}
function drawBudget(box, d) {
  var b = d.budget || null, L = d.ledger || null;
  if (!b && !L) { box.innerHTML = ''; return; }
  var tiles = [];
  if (b && b.summer) {
    tiles.push(FB.kpi('Summer budget', FB.money(b.summer.mid), { sub: '25-75%: ' + moneyRange(b.summer.lo, b.summer.hi) }));
    tiles.push(FB.kpi('Next window', moneyRange((b.next || {}).lo, (b.next || {}).hi), { sub: esc((b.next || {}).window || '') }));
  }
  if (b && isNum(b.squad_mv)) tiles.push(FB.kpi('Squad value (Sofascore)', FB.money(b.squad_mv), { sub: isNum(b.squad_mv_n) ? b.squad_mv_n + ' of ' + (b.squad_n || 0) + ' valued (Sofascore)' : '' }));
  if (L && L.last12) tiles.push(FB.kpi('Net spend, 12 months', FB.money(L.last12.net), { sub: 'spent ' + FB.money(L.last12.spend) + ' · sold ' + FB.money(L.last12.income) }));
  var l12 = (L || {}).last12 || {};
  box.innerHTML = FB.secHead('Budget and ledger', 'The budget is a model of what this club spends in a window, from its previous window, its league\'s and its own strength' + (b && b.squad_mv ? ' and its squad\'s market value (Sofascore)' : '') + '; fitted across the followed clubs (out of sample, half the clubs land inside their 25-75% range). Not a club statement; wages are unknown.', '', 'Money') +
    (tiles.length ? FB.kpis(tiles) : '') +
    (isNum(l12.value_added) ? FB.note('<span>Last 12 months: signings worth ' + FB.money(l12.fair_in) + ' at fair value for ' + FB.money(l12.spend) + ' in fees; sales worth ' + FB.money(l12.fair_out) + ' for ' + FB.money(l12.income) + ': value added in the market <b>' + (l12.value_added >= 0 ? '+' : '−') + FB.money(Math.abs(l12.value_added)) + '</b>. On the pitch: signings ' + num(l12.gar_in, 1) + ' GAR a season, departures ' + num(l12.gar_out, 1) + '.') : '') +
    ((L && (L.windows || []).length) ? FB.grid(FB.card('By window', 'Fees spent and received.', FB.chartBox('cl-win', 260, 'Spend and income by window'), { span: 6 }) + FB.card('Windows', '', '<div id="cl-wint"></div>', { span: 6, flush: true }), 'fb-mt') : '') +
    (L ? FB.grid(FB.card('In', 'Signings with the fee, our fair fee and a grade as the buyer.', '<div id="cl-in"></div>', { span: 6, flush: true }) + FB.card('Out', 'Departures, graded as the seller.', '<div id="cl-out"></div>', { span: 6, flush: true }), 'fb-mt') : '');
  if (!L) return;
  var ws = (L.windows || []).slice();
  if (ws.length) {
    var asc = ws.slice().reverse();
    QKC.bar(box.querySelector('#cl-win'), { legend: true, valName: 'Transfer fees', catName: 'Transfer window', fmt: function (v) { return FB.money(v * 1e6); }, cats: asc.map(function (w) { return w.label; }),
      series: [{ name: 'Spent', data: asc.map(function (w) { return Math.round((w.spend || 0) / 1e5) / 10; }), color: QK.cssVar('--c-2') }, { name: 'Received', data: asc.map(function (w) { return Math.round((w.income || 0) / 1e5) / 10; }), color: QK.cssVar('--c-1') }], label: 'Spend and income by window' });
    FB.table(box.querySelector('#cl-wint'), [
      { key: 'label', label: 'Window', fmt: function (v, r) { return esc(v) + (r.complete ? '' : ' <span class="qk-muted" data-tip="From players\' transfer histories, still filling in">(partial)</span>'); } },
      { key: 'spend', label: 'Spent', num: true, fmt: function (v) { return FB.money(v); } }, { key: 'income', label: 'Sold', num: true, fmt: function (v) { return FB.money(v); } },
      { key: 'net', label: 'Net', num: true, fmt: function (v) { return FB.money(v); } },
      { key: 'n_in', label: 'In / out', num: true, fmt: function (v, r) { return (v || 0) + ' / ' + (r.n_out || 0); } }, { key: 'undisclosed', label: 'Undiscl.', num: true }
    ], ws, { caption: 'Windows' });
  }
  var cols = function (side) { return [
    { key: 'date', label: 'Date', fmt: function (v) { return '<span class="fb-num">' + esc(v) + '</span>'; } },
    { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return FB.playerLink(r.pid, v) + ' <span class="qk-muted">' + esc(r.role || '') + '</span>'; } },
    { key: 'club_name', label: side === 'in' ? 'From' : 'To', fmt: function (v, r) { return FB.clubLink(r.club, v); } },
    { key: 'kind', label: 'Type', fmt: function (v) { return esc(DEAL_KIND[v] || v); } },
    { key: 'fee', label: 'Fee', num: true, fmt: function (v, r) { return r.kind === 'fee' ? FB.money(v) : r.kind === 'free' ? 'Free' : '—'; } },
    { key: 'fair', label: 'Fair fee', num: true, fmt: function (v) { return FB.money(v); } },
    { key: 'post_min', label: 'Min since', num: true },
    { key: 'grade', label: 'Grade', fmt: function (v) { return grade(v); } }
  ]; };
  if ((L.in || []).length) FB.table(box.querySelector('#cl-in'), cols('in'), L.in.slice(0, 20), { caption: 'Signings' }); else box.querySelector('#cl-in').innerHTML = '<p class="fb-muted" style="padding:12px 16px">None in our data.</p>';
  if ((L.out || []).length) FB.table(box.querySelector('#cl-out'), cols('out'), L.out.slice(0, 20), { caption: 'Departures' }); else box.querySelector('#cl-out').innerHTML = '<p class="fb-muted" style="padding:12px 16px">None in our data.</p>';
}

})(window.FB);
