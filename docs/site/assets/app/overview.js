/* The Quant Footballer — Overview (#/): every competition at once, on kit v3 "Matchday" (dark only). The Rink overview
 * (docs/rink/assets/js/rk-overview.js) is the reference page; docs/_design/MIGRATION_V3.md has the steps.
 *
 *   ticker         the broadcast-black ticker: today's live, coming and finished matches by competition
 *   greeting       QK.greeting with the match to watch (QK.featureCard: our pre-match chance and what it means)
 *   stat tiles     matches today, the biggest league's title favourite and Europe's (our chance), the top-rated club on
 *                  the pooled scale, the top scorer across competitions
 *   what to watch  game cards for one day (our home / draw / away chance before kick-off, the score and xG after),
 *                  each with a one-line reason, picked by how close and how big the match is; the day and the
 *                  competition family are pickers. No market anywhere on this page.
 *   who's hot      QK.hotRow: goals, assists, rating, finishing and the strongest club, one name each
 *   new here?      three things to know, beside a "How sure are we?" teaser read from data/calibration.json (shown only
 *                  when the file is there)
 *   title races    every open race's favourite and our chance (chance bars, ours only), and the big five leagues'
 *                  title chances run by run (forecast lines with end labels)
 *   leaders        goals against xG across competitions; the strongest clubs on the pooled scale; national teams
 *   leagues        the leagues at a glance: progress, leader, our favourite, top scorer
 *
 * Football has no live model: a match in play keeps our pre-match chance, labelled "our pre-game chance" (FB.toGame
 * sets pre_only), as on the Home page and the ticker.
 *
 * Reads competitions.json (FB.INDEX), hub.json, lab/leaders.json, the big leagues' history.json, pool.json,
 * nations.json and calibration.json (when present); each card degrades on its own. While a match is live, hub.json is
 * re-read every minute. A match a cached snapshot still marks live 12 hours after kick-off is not counted as live
 * (FB.staleLive). */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, pct = FB.pct, num = FB.num;

var BIG = ['premier-league', 'la-liga', 'serie-a', 'bundesliga', 'ligue-1'];
var FAM_CHIPS = [['all', 'All'], ['league', 'Leagues'], ['cup', 'Continental'], ['domestic', 'National cups'], ['super', 'Super cups'], ['international', 'National teams']];
var view = { fam: 'all', day: null, race: 'premier-league' };
var FORM = null;   // team id -> { comp, form } from pool.json (league form, oldest first)
/* How big a match is, by competition: the world's most-watched first, so "what to watch" is not a list of the
   closest matches in the smallest leagues. */
var PROM = {
  'world-cup': 18, euro: 16, 'champions-league': 16, 'copa-america': 13, 'premier-league': 14, 'la-liga': 12, 'serie-a': 11, bundesliga: 11,
  'ligue-1': 9, 'europa-league': 9, libertadores: 9, 'nations-league': 8, 'club-world-cup': 10, 'fa-cup': 6, 'copa-del-rey': 5, 'dfb-pokal': 5,
  'coppa-italia': 5, brasileirao: 6, mls: 5, 'liga-argentina': 5, eredivisie: 5, 'primeira-liga': 5, 'conference-league': 5, 'wc-qual-uefa': 6, 'wc-qual-conmebol': 7
};

function allHub(h) {
  var out = [];
  var days = (h || {}).days || {};
  Object.keys(days).forEach(function (k) { (days[k] || []).forEach(function (m) { out.push(m); }); });
  return out;
}
function isLive(m) { return (m.status === 'live' || m.status === 'inprogress') && !FB.staleLive(m); }
function famOfSlug(slug) { return FB.familyOf(FB.comp(slug)); }
function inSeason(c) { return c.ok && !FB.isLastEdition(c); }
function evening() { var h = new Date().getHours(); return h >= 15 || h < 5; }
/* How much a match is worth watching: live first, then close calls in the biggest competitions, then soonest. */
function watchRank(m) {
  var g = FB.toGame(m, m.comp);
  var s = QK.watchScore(g);
  if (s < -1e8) s = 0;
  return s + (PROM[m.comp] || 0) + (isLive(m) ? 10 : 0) - (m.status === 'postponed' || m.status === 'cancelled' ? 50 : 0);
}

FB.route('overview', function (el) {
  var comps = FB.comps();
  var d = new Date();
  var nIn = comps.filter(inSeason).length;
  var when = evening() ? 'tonight' : 'today';
  el.innerHTML =
    '<div class="qk-ticker fb-ov-ticker" id="ov-ticker" aria-label="Scores and our chances" hidden></div>' +
    '<div id="ov-hero">' + QK.greeting({ date: 'Football · ' + FB.DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + FB.MONTHS[d.getMonth()] + ' · ' + nIn + ' competitions in season',
      title: esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in football ' + when + '.',
      lede: 'Our chance for every match, title and cup chances from 30,000 simulated seasons, expected goals, and one page for every club and player across all ' + comps.filter(function (c) { return c.ok; }).length + ' competitions, explained in plain English.',
      ctas: [{ label: 'All matches', href: '#/matches' }, { label: 'Competitions', href: '#/competitions', ghost: true }] }) + '</div>' +
    '<div class="fb-ov-quick">' + BIG.concat(['champions-league', 'brasileirao', 'mls', 'liga-argentina', 'libertadores']).filter(function (s) { return FB.comp(s) && FB.comp(s).ok; }).map(function (s) {
      return '<a class="qk-chip" href="' + esc(FB.href.comp(s)) + '">' + esc(FB.compName(s, true)) + '</a>';
    }).join('') + '<a class="qk-chip" href="#/competitions">All ' + comps.filter(function (c) { return c.ok; }).length + ' →</a></div>' +
    '<div id="ov-kpis" class="fb-ov-kpis">' + QK.skeleton('lines', 2) + '</div>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: '<span id="ov-gh">Today</span>', html: true,
        sub: '<span id="ov-day-sub">Our chance for each side, with a line on why it’s worth your time. Kick-off in your time zone; during a match the card keeps our pre-match chance.</span>',
        actions: '<span id="ov-days"></span><a class="qk-more" href="#/matches">Every match</a>' }) +
      '<div class="qk-chips scroll" id="ov-fam" role="group" aria-label="Competition family">' + FAM_CHIPS.map(function (f) {
        return '<button class="qk-chip" type="button" data-value="' + f[0] + '" aria-pressed="' + (f[0] === view.fam) + '">' + esc(f[1]) + ' <span class="n" data-n="' + f[0] + '"></span></button>';
      }).join('') + '</div>' +
      '<div id="ov-cards" class="qk-watch fb-mt">' + QK.skeleton('card', 3) + '</div>' +
      '<div id="ov-more" class="fb-cap"></div></section>' +
    '<section class="qk-section" id="ov-hot-sec">' + QK.sectionHead({ kicker: 'Who’s hot', title: 'Leading the way this season', sub: 'One name for each, across every competition, and what the number actually means.' }) +
      '<div id="ov-hot">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="qk-section qk-gside fb-ov-new" id="ov-new"><div id="ov-sure" hidden></div><div>' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against others in the same role (centre-backs with centre-backs, strikers with strikers): 90th means better than 90 in 100.',
      'Every forecast is checked against what happened. <a class="qk-link" href="#/model/calibration">The record is on the Model page.</a>'] }) + '</div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Season simulations', title: 'Who wins it', sub: 'Our chances from 30,000 simulated seasons: each open competition’s favourite, and how the big five title races have moved run by run.' }) +
      FB.grid(
        FB.card('Favourites', 'Our chance that each open competition’s favourite wins it.', '<div id="ov-races"></div>', { span: 5, foot: '<span>Up to fourteen open races</span><a href="#/competitions">Every competition →</a>' }) +
        FB.card('The title race, run by run', 'Our title chance after each hourly model run, for the top five in the league.', '<div class="fb-toolbar" id="ov-race-pick"></div>' + FB.chartBox('ov-race', 340, 'Title chances over time'), { span: 7 })
      ) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Leaderboards', title: 'Goals, chances and the strongest sides', sub: 'Across every competition this season, and every club and national team on one scale.', actions: '<a class="qk-more" href="#/players/leaders">Players</a>' }) +
      FB.grid(
        FB.card('Goals against expected', 'The leading scorers across every competition: goals scored and the expected goals (xG) of their shots.', FB.chartBox('ov-goals', 360, 'Goals and xG of the top scorers') +
          FB.note('<b>xG</b> is how many goals an average finisher would score from the same shots. Well above it is great finishing or good luck; one season rarely tells the two apart.'), { span: 6 }) +
        '<div class="qk-span-3">' + FB.card('Strongest clubs', 'Our rating: expected points a game against an average side.', '<div id="ov-pool"></div>', { flush: true, foot: '<span></span><a href="#/clubs">All clubs →</a>' }) + '</div>' +
        '<div class="qk-span-3">' + FB.card('Strongest national teams', 'Our international rating, the same scale.', '<div id="ov-nations"></div>', { flush: true, foot: '<span></span><a href="#/clubs/nations">All national teams →</a>' }) + '</div>'
      ) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Leagues', title: 'Every league at a glance', sub: 'How far each league has gone, who leads, our title favourite and the top scorer.', actions: '<a class="qk-more" href="#/competitions">Competitions</a>' }) +
      FB.card('', '', '<div id="ov-leagues"></div>', { flush: true }) + '</section>' +
    '<section class="qk-section">' + FB.card('Between editions', 'Competitions with no edition in progress: the last one, as it finished.', '<div id="ov-last" class="fb-ov-last"></div>') + '</section>';

  QK.chips(el.querySelector('#ov-fam'), function (vals) { view.fam = vals[0] || 'all'; drawCards(el, HUB); });

  var HUB = null, POOL = null;
  var hubP = FB.load('hub.json');
  var poolP = FB.load('pool.json');
  var p = Promise.all([hubP, poolP]).then(function (arr) {
    if (!FB.alive(el)) return;
    HUB = arr[0] || { days: {} };
    POOL = arr[1];
    FORM = formMap(POOL);
    drawHero(el, HUB);
    drawCards(el, HUB);
    drawTicker(el, HUB);
    drawKpis(el, HUB, POOL);
    drawLeaders(el, HUB);
    drawPool(el, POOL);
    FB.load('lab/leaders.json').then(function (board) { if (FB.alive(el)) drawHot(el, board, HUB, POOL); });
  });
  drawSure(el);
  drawRaces(el);
  drawRaceHistory(el);
  drawLeagues(el);
  drawLast(el);
  FB.load('nations.json').then(function (n) { if (FB.alive(el)) drawNations(el, n); });

  /* live: re-read the scoreboard every minute while anything is in play or about to start */
  FB.interval(function () {
    var soon = allHub(HUB).some(function (m) { var t = FB.parseDate(m.date); return isLive(m) || (m.status !== 'finished' && t && Math.abs(t - Date.now()) < 15 * 60000); });
    if (!soon) return;
    FB.reload('hub.json').then(function (h) { if (!FB.alive(el) || !h) return; HUB = h; FB.hubLive(h); drawCards(el, HUB); drawTicker(el, HUB); drawKpis(el, HUB, POOL); });
  }, 60000);
  return p;
});

/* ── league form for the cards (pool.json form_results, oldest first: checked against the fixtures) */
function formMap(pool) {
  var out = {};
  ((pool || {}).clubs || []).forEach(function (c) { if (c.team_id && (c.form_results || []).length) out[String(c.team_id)] = { comp: c.comp, form: c.form_results.join('') }; });
  return out;
}
function extraFor(m, why) {
  var h = FB.tidFromCrest(m.crests && m.crests[0]), a = FB.tidFromCrest(m.crests && m.crests[1]);
  var fh = FORM && h && FORM[String(h)], fa = FORM && a && FORM[String(a)];
  return {
    home_form: fh && fh.comp === m.comp ? fh.form : null,
    away_form: fa && fa.comp === m.comp ? fa.form : null,
    why: !!why
  };
}

/* ── the greeting's match to watch: the best match still to come in the next two days (our pre-match chance) */
function drawHero(el, h) {
  var box = el.querySelector('#ov-hero');
  if (!box) return;
  var now = Date.now();
  var cands = allHub(h).filter(function (m) { var t = FB.parseDate(m.date); return m.status === 'scheduled' && m.model && isNum(m.model.h) && t && t - now > -5 * 60000 && t - now < 48 * 3600e3; });
  var best = cands.map(function (m) { return [watchRank(m), m]; }).sort(function (a, b) { return b[0] - a[0]; })[0];
  if (!best) return;
  var m = best[1], g = FB.toGame(m, m.comp);
  var c = FB.comp(m.comp) || {};
  var rel = FB.relDay(m.date);
  var d = new Date();
  box.innerHTML = QK.greeting({ date: 'Football · ' + FB.DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + FB.MONTHS[d.getMonth()] + ' · ' + FB.comps().filter(inSeason).length + ' competitions in season',
    title: esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in football ' + (evening() ? 'tonight' : 'today') + '.',
    lede: 'Our chance for every match, title and cup chances from 30,000 simulated seasons, expected goals, and one page for every club and player across all ' + FB.comps().filter(function (x) { return x.ok; }).length + ' competitions, explained in plain English.',
    ctas: [{ label: 'All matches', href: '#/matches' }, { label: 'Competitions', href: '#/competitions', ghost: true }],
    side: QK.featureCard(g, { kicker: (c.name || FB.compName(m.comp)) + (g.note ? ' · ' + g.note : ''), scribble: rel === 'Today' ? 'Our pick ' + (evening() ? 'tonight' : 'today') + '!' : 'Our pick for ' + (rel === 'Tomorrow' ? 'tomorrow' : rel) + '!' }) });
}

/* ── one day's matches: "what to watch" */
function dayList(h) {
  var by = {};
  allHub(h).forEach(function (m) { var k = FB.localDay(m.date); if (k) (by[k] = by[k] || []).push(m); });
  return by;
}
function drawCards(el, h) {
  var by = dayList(h);
  var keys = Object.keys(by).sort();
  var t = FB.today();
  if (!view.day || keys.indexOf(view.day) < 0) view.day = keys.indexOf(t) >= 0 ? t : (keys.filter(function (k) { return k > t; })[0] || keys[keys.length - 1] || t);
  var days = el.querySelector('#ov-days');
  if (days) {
    var lo = shiftDay(t, -1), hi = shiftDay(t, 2);
    var shown = keys.filter(function (k) { return (k >= lo && k <= hi) || k === view.day; });
    days.innerHTML = shown.length > 1 ? FB.seg('ov-day', shown.map(function (k) { return [k, FB.relDay(k + 'T12:00:00')]; }), view.day, 'Day') : '';
    FB.wireSeg(days, 'ov-day', function (v) { view.day = v; drawCards(el, h); });
  }
  var list = (by[view.day] || []).slice();
  var counts = { all: list.length };
  list.forEach(function (m) { var f = famOfSlug(m.comp); counts[f] = (counts[f] || 0) + 1; });
  Array.prototype.forEach.call(el.querySelectorAll('#ov-fam [data-n]'), function (n) { n.textContent = counts[n.getAttribute('data-n')] || 0; });
  if (view.fam !== 'all') list = list.filter(function (m) { return famOfSlug(m.comp) === view.fam; });
  var rk = {};
  list.forEach(function (m) { rk[m.id] = watchRank(m); });
  list.sort(function (a, b) { return (rk[b.id] - rk[a.id]) || String(a.date).localeCompare(String(b.date)); });
  var gh = el.querySelector('#ov-gh');
  var dayName = view.day === t ? 'today' : FB.relDay(view.day + 'T12:00:00');
  if (gh) gh.textContent = list.length ? (list.length === 1 ? 'One match' : list.length + ' matches') + (view.day === t ? ' on the slate' : ' · ' + dayName) : (view.day === t ? 'Today' : dayName);
  var box = el.querySelector('#ov-cards');
  if (!box) return;
  if (!list.length) { box.innerHTML = '<div style="grid-column:1/-1">' + FB.empty('No matches', view.fam === 'all' ? 'Nothing scheduled across the competitions followed on this day.' : 'Nothing from this family on this day.') + '</div>'; FB.set('ov-more', ''); return; }
  var LIM = 9;
  box.innerHTML = list.slice(0, LIM).map(function (m) { return FB.matchCard(m, m.comp, extraFor(m, true)); }).join('');
  var more = el.querySelector('#ov-more');
  if (more) more.innerHTML = list.length > LIM ? 'Our nine picks of ' + list.length + ' on this day. <a href="' + esc(FB.href.matches({ d: view.day, f: view.fam === 'all' ? null : view.fam })) + '">See every match →</a>' : '';
}
function shiftDay(k, n) { var d = FB.parseDate(k + 'T12:00:00'); d.setDate(d.getDate() + n); return FB.localDay(d); }

/* ── the ticker: live first, then today's coming matches, then today's results (kit QK.ticker by league) */
function drawTicker(el, h) {
  var box = el.querySelector('#ov-ticker');
  if (!box) return;
  var t = FB.today();
  var list = allHub(h).filter(function (m) { return isLive(m) || FB.localDay(m.date) === t; });
  if (!list.length) { box.hidden = true; return; }
  var rank = {};
  FB.comps().forEach(function (c, i) { rank[c.slug] = i; });
  list.sort(function (a, b) { return (rank[a.comp] === undefined ? 999 : rank[a.comp]) - (rank[b.comp] === undefined ? 999 : rank[b.comp]) || String(a.date).localeCompare(String(b.date)); });
  var games = list.slice(0, 40).map(function (m) { return FB.toGame(m, m.comp); });
  box.innerHTML = QK.ticker(games, { group: 'league', max: 40, pill: false });
  box.hidden = false;
}

/* ── stat tiles: ours first, no market */
function drawKpis(el, h, pool) {
  var all = allHub(h);
  var t = FB.today();
  var todays = all.filter(function (m) { return FB.localDay(m.date) === t; });
  var live = all.filter(isLive);
  var box = el.querySelector('#ov-kpis');
  if (!box) return;
  var tiles = [];
  tiles.push(FB.kpi(live.length ? 'Live now' : 'Matches today', String(live.length || todays.length), {
    sub: live.length ? todays.length + ' on the slate today'
      : todays.filter(function (m) { return m.status === 'finished'; }).length + ' finished · ' + todays.filter(function (m) { return m.status === 'scheduled'; }).length + ' to come',
    cls: live.length ? 'fb-ov-livetile' : '' }));
  var lead = BIG.map(FB.comp).filter(function (c) { return c && inSeason(c) && c.favourite && isNum(c.p_favourite); })[0];
  if (lead) tiles.push(FB.kpi((lead.short_name || lead.name) + ' favourite', esc(lead.favourite) + ' ' + pct(lead.p_favourite), { signal: true, text: true, href: FB.href.comp(lead.slug, 'odds'),
    sub: 'our title chance, from 30,000 simulated seasons', tip: 'Our chance of winning the league in the season simulation' }));
  var ucl = FB.comp('champions-league');
  if (ucl && inSeason(ucl) && ucl.favourite && isNum(ucl.p_favourite)) tiles.push(FB.kpi('Champions League favourite', esc(ucl.favourite) + ' ' + pct(ucl.p_favourite), { text: true, href: FB.href.comp(ucl.slug, 'odds'),
    sub: 'our chance to lift the trophy', tip: 'Our chance of winning the Champions League in the simulation of the rest of the competition' }));
  var clubs = ((pool || {}).clubs || []).filter(function (c) { return (c.in_league || (c.played || 0) > 0) && isNum(c.strength); }).sort(function (a, b) { return b.strength - a.strength; });
  if (clubs.length) tiles.push(FB.kpi('Top-rated club', esc(clubs[0].team) + ' ' + num(clubs[0].strength, 2), { text: true, href: clubs[0].team_id ? FB.href.club(clubs[0].team_id) : null,
    sub: 'points a game we’d expect against an average side', tip: 'Our pooled rating across leagues: the points a game this club would expect against an average side' }));
  var g = (((h || {}).leaders || {}).goals || [])[0];
  if (g) tiles.push(FB.kpi('Top scorer', esc(g.name) + ' ' + g.value, { text: true, href: FB.href.player(g.id),
    sub: esc(g.comp_name || FB.compName(g.comp, true)) + (isNum(g.xg) ? ' · from ' + num(g.xg, 1) + ' expected goals' : ''), tip: 'Goals in one competition this season, the most of any player' }));
  box.innerHTML = FB.kpis(tiles.slice(0, 5));
}

/* ── who's hot: one name each, across every competition (lab/leaders.json; hub.json's lists when it is missing) */
function drawHot(el, board, hub, pool) {
  var box = el.querySelector('#ov-hot');
  if (!box) return;
  var L = board && board.scopes && board.scopes.all ? board.scopes.all : null;
  var H = (hub || {}).leaders || {};
  var goals = (L && L.goals) || H.goals || [], assists = (L && L.assists) || H.assists || [];
  var rating = ((L && L.rating) || (H.rating || []).filter(function (r) { return (r.minutes || 0) >= 450; }));
  var items = [], used = {};
  /* one name each: a player already in the row gives way to the next one on that list */
  var pick = function (list, i) { var out = list.filter(function (r) { return r && !used[String(r.id)]; }); return out[i || 0]; };
  var use = function (r) { if (r) used[String(r.id)] = 1; return r; };
  goals = goals.slice(); assists = assists.slice(); rating = rating.slice();
  var g0 = use(pick(goals)), a0 = use(pick(assists)), r0 = use(pick(rating));
  var whereOf = function (r) { return r.team || r.comp_name || ''; };
  /* the next best when this is the leader; when the leader is already in the row, say who is ahead instead */
  var nextOf = function (list, me, f) { if (list[0] !== me) return null; var n = list[1]; return n ? { name: n.name, value: f ? f(n.value) : n.value } : null; };
  var behind = function (list, me, f) { return list[0] && list[0] !== me ? 'Behind only ' + list[0].name + ' (' + (f ? f(list[0].value) : list[0].value) + '). ' : ''; };
  var top = function (list) { return list[0] || null; };
  if (g0) items.push({ sport: 'football', title: g0 === top(goals) ? 'Most goals' : 'Goals', name: g0.name, value: g0.value, unit: 'goals' + (L ? ' in all competitions' : ''), href: FB.href.player(g0.id),
    next: nextOf(goals, g0),
    expl: isNum(g0.xg) ? whereOf(g0) + '. From shots worth ' + num(g0.xg, 1) + ' expected goals: ' + (g0.value - g0.xg >= 2 ? 'finishing well above an average shooter.' : g0.value - g0.xg <= -2 ? 'unlucky or wasteful in front of goal.' : 'about what the chances were worth.') : whereOf(g0) + '.' });
  if (a0) items.push({ sport: 'football', title: a0 === top(assists) ? 'Most assists' : 'Assists', name: a0.name, value: a0.value, unit: 'assists', href: FB.href.player(a0.id),
    next: nextOf(assists, a0),
    expl: behind(assists, a0) + (isNum(a0.xa) ? whereOf(a0) + '. Passes worth ' + num(a0.xa, 1) + ' expected assists: the chances created, whatever the finish.' : whereOf(a0) + '.') });
  if (r0) items.push({ sport: 'football', title: r0 === top(rating) ? 'Best rating' : 'Rating', name: r0.name, value: num(r0.value, 2), unit: 'average match rating', href: FB.href.player(r0.id),
    next: nextOf(rating, r0, function (v) { return num(v, 2); }),
    expl: behind(rating, r0, function (v) { return num(v, 2); }) + 'Out of 10, weighted by minutes' + (isNum(r0.minutes) ? ' over ' + FB.int(r0.minutes) + ' minutes' : '') + '. A 7 is a good game; above 8 is rare over a season.' });
  var fin = goals.filter(function (r) { return isNum(r.xg) && r.value >= 5 && !used[String(r.id)]; }).map(function (r) { return [r.value - r.xg, r]; }).sort(function (a, b) { return b[0] - a[0]; });
  if (fin[0] && fin[0][0] > 0) items.push({ sport: 'football', title: 'Hottest finisher', name: fin[0][1].name, value: '+' + num(fin[0][0], 1), unit: 'goals above expected', href: FB.href.player(fin[0][1].id),
    next: fin[1] ? { name: fin[1][1].name, value: '+' + num(fin[1][0], 1) } : null,
    expl: fin[0][1].value + ' goals from ' + num(fin[0][1].xg, 1) + ' xG. Hot streaks like this rarely last: finishing above xG mostly evens out.' });
  var clubs = ((pool || {}).clubs || []).filter(function (c) { return (c.in_league || (c.played || 0) > 0) && isNum(c.strength); }).sort(function (a, b) { return b.strength - a.strength; });
  if (clubs[0]) items.push({ sport: 'football', title: 'Strongest club', name: clubs[0].team, value: num(clubs[0].strength, 2), unit: 'points a game, our rating', href: clubs[0].team_id ? FB.href.club(clubs[0].team_id) : null,
    next: clubs[1] ? { name: clubs[1].team, value: num(clubs[1].strength, 2) } : null,
    expl: 'What we’d expect it to take from a game against an average side anywhere. ' + (clubs[0].comp_name ? clubs[0].comp_name + '.' : '') });
  box.innerHTML = items.length ? QK.hotRow(items) : FB.empty('No leaders yet', 'The leaders appear once the season’s first matches are in.');
}

/* ── How sure are we? (teaser): the match model's record from data/calibration.json, shown only when the file exists */
function calibOf(j) {
  if (!j) return null;
  return QK.calib.find(j) || QK.calib.find(j.match_model) || QK.calib.find(j.overall) || QK.calib.find(j.model);
}
FB.calibOf = calibOf;
function drawSure(el) {
  FB.load('calibration.json').then(function (cj) {
    var box = el.querySelector('#ov-sure'), sec = el.querySelector('#ov-new');
    if (!box || !FB.alive(el)) return;
    var cb = calibOf(cj);
    if (!cb || !cb.bins.length) { box.hidden = true; if (sec) sec.classList.add('solo'); return; }
    var subj = (cj && cj.subject) || 'the home side';
    var big = cb.bins.slice().sort(function (a, b) { return b.n - a.n; })[0];
    box.hidden = false;
    if (sec) sec.classList.remove('solo');
    box.innerHTML = '<article class="qk-card" style="height:100%"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">When we say ' + Math.round(big.mean_p * 100) + '%, it happens ' + Math.round(big.freq * 100) + '% of the time</h3>' +
      '<p style="margin:0 0 6px;color:var(--ink-2)">Our most common call puts ' + esc(subj) + ' at ' + Math.round(big.lo * 100) + '–' + Math.round(big.hi * 100) + '%. Across ' + QK.fmt.num(big.n) + ' matches like that, ' + esc(subj) + ' won ' + QK.fmt.pct(big.freq, 1) + '.</p>' +
      (isNum(cb.brier) ? QK.note('<b>Brier score ' + cb.brier.toFixed(3) + '</b> over ' + QK.fmt.num(cb.n) + ' matches: 0 is perfect, and lower is better. With the draw in play, football is hard to call, so small gains count.') : '') +
      '<a class="qk-more" style="display:inline-block;margin-top:14px" href="#/model/calibration">The full record</a></div></article>';
  });
}

/* ── title races: our chance only (no market on the overview) */
function drawRaces(el) {
  var rows = FB.comps().filter(function (c) { return inSeason(c) && c.favourite && isNum(c.p_favourite) && !c.complete && c.p_favourite < 0.995; })
    .sort(function (a, b) { return b.p_favourite - a.p_favourite; }).slice(0, 14);
  var box = el.querySelector('#ov-races');
  if (!rows.length) { box.innerHTML = FB.empty('No open races', 'Every competition followed is decided or between editions.'); return; }
  box.innerHTML = FB.chances(rows.map(function (c) {
    return { label: c.favourite, sub: c.short_name || c.name, p: c.p_favourite, href: FB.href.comp(c.slug, 'odds'), mark: { name: c.favourite } };
  }), { max: 1, key: false }) + FB.note('Even a 70% favourite misses about 3 times in 10. The bars are our chances only.');
}
function drawRaceHistory(el) {
  var avail = BIG.filter(function (s) { var c = FB.comp(s); return c && inSeason(c) && FB.hasFile(s, 'history'); });
  var pick = el.querySelector('#ov-race-pick');
  if (!avail.length) { FB.set('ov-race', FB.empty('No history yet', 'Title chances are recorded after each model run.')); return; }
  if (avail.indexOf(view.race) < 0) view.race = avail[0];
  pick.innerHTML = FB.seg('ov-race-seg', avail.map(function (s) { return [s, FB.compName(s, true)]; }), view.race, 'League');
  FB.wireSeg(pick, 'ov-race-seg', function (v) { view.race = v; draw(); });
  function draw() {
    var slug = view.race;
    FB.compFiles(slug, ['history']).then(function (d) {
      var box = el.querySelector('#ov-race');
      if (!box || !FB.alive(el)) return;
      var snaps = ((d.history || {}).snapshots || []).filter(function (s) { return s.title && FB.parseDate(s.ts); });
      if (snaps.length < 2) { box.style.height = 'auto'; box.innerHTML = FB.empty('Not enough runs yet', 'The line appears after two model runs.'); return; }
      box.style.height = '';
      var last = snaps[snaps.length - 1].title;
      var teams = Object.keys(last).sort(function (a, b) { return last[b] - last[a]; }).slice(0, 5).filter(function (t) { return last[t] > 0.005; });
      if (!teams.length) teams = Object.keys(last).slice(0, 3);
      QKC.forecast(box, {
        xType: 'time', x: snaps.map(function (s) { return s.ts; }),
        xFmt: function (v) { var dd = new Date(v); return isNaN(dd.getTime()) ? '' : dd.getDate() + ' ' + FB.MONTHS[dd.getMonth()]; },
        xLabel: function (v) { return 'Model run · ' + FB.fmtStamp(new Date(v)); },
        xName: 'Model run (date)', yName: 'Our title chance', label: 'Our title chances by model run, ' + FB.compName(slug),
        series: teams.map(function (t, i) { return { name: t, label: shortName(t, teams), data: snaps.map(function (s) { return isNum(s.title[t]) ? s.title[t] : 0; }), ours: false, color: QK.cssVar('--c-' + (i + 1)) }; })
      });
    });
  }
  draw();
}

/* A line's end label: the club's name, or one word of it when long (the first, or the last when two clubs share the first). */
function shortName(t, all) {
  if (t.length <= 12) return t;
  var w = t.split(' '), first = w[0];
  var shared = all.filter(function (x) { return x !== t && x.split(' ')[0] === first; }).length > 0;
  return shared ? w[w.length - 1] : first;
}

/* ── leaders: goals v xG */
function drawLeaders(el, h) {
  var L = ((h || {}).leaders || {}).goals || [];
  var box = el.querySelector('#ov-goals');
  if (!box) return;
  var top = L.slice(0, 10);
  if (!top.length) { box.style.height = 'auto'; box.innerHTML = FB.empty('No player data yet'); return; }
  QKC.bar(box, {
    horizontal: true, legend: true, labelWidth: 150, fmt: function (v) { return num(v, 0); }, valName: 'Goals and xG this season', catName: 'Player',
    cats: top.map(function (p) { return p.name + ' (' + (p.comp_name || FB.compName(p.comp, true)) + ')'; }),
    series: [{ name: 'Goals', data: top.map(function (p) { return p.value; }), color: QK.cssVar('--c-1') }, { name: 'xG', data: top.map(function (p) { return isNum(p.xg) ? Math.round(p.xg * 10) / 10 : null; }), color: QK.cssVar('--c-3') }],
    hrefs: top.map(function (p) { return FB.href.player(p.id); }), label: 'Top scorers: goals and xG'
  });
}

/* ── leagues at a glance (leaderboard) */
function drawLeagues(el) {
  var rows = FB.comps().filter(function (c) { return c.ok && FB.familyOf(c) === 'league'; }).map(function (c) {
    return { slug: c.slug, name: c.name, country: c.country || '', c: c, prog: c.games_total ? (c.games_played || 0) / c.games_total : null,
      leader: (c.leader || {}).team || '', pts: (c.leader || {}).pts, fav: c.favourite, p: isNum(c.p_favourite) ? c.p_favourite : null,
      scorer: (c.top_scorer || {}).name, sid: (c.top_scorer || {}).id, goals: (c.top_scorer || {}).goals };
  });
  QK.leaderboard(el.querySelector('#ov-leagues'), {
    dense: true, caption: 'Leagues at a glance',
    columns: [
      { key: 'name', label: 'League', type: 'entity', sub: 'country', href: function (r) { return FB.href.comp(r.slug); } },
      { key: 'prog', label: 'Season played', type: 'bar', max: 1, fmt: function (v, r) { return isNum(v) ? Math.round(v * 100) + '%' : '—'; } },
      { key: 'leader', label: 'Leader', fmt: function (v, r) { return v ? esc(v) + ' <span class="qk-muted fb-num">' + r.pts + ' pts</span>' : '—'; } },
      { key: 'p', label: 'Our favourite', num: true, fmt: function (v, r) { return r.fav && isNum(v) ? esc(r.fav) + ' <b class="fb-num fb-ov-sig">' + pct(v) + '</b>' : '—'; } },
      { key: 'goals', label: 'Top scorer', num: true, fmt: function (v, r) { return r.scorer ? (r.sid ? FB.playerLink(r.sid, r.scorer) : esc(r.scorer)) + ' <b class="fb-num">' + v + '</b>' : '—'; } }
    ], rows: rows
  });
}

function leadList(items) {
  return '<ul class="fb-ov-lead">' + items.map(function (x, i) {
    return '<li><span class="n">' + (x.rank || i + 1) + '</span><span class="who">' + x.who + (x.sub ? '<span class="s">' + esc(x.sub) + '</span>' : '') + '</span><span class="v">' + esc(x.v) + '</span></li>';
  }).join('') + '</ul>';
}
function drawPool(el, pool) {
  var box = el.querySelector('#ov-pool');
  if (!box) return;
  /* clubs with no rated matches yet (cup entrants seen only in a draw) carry the prior, not a measured strength */
  var clubs = ((pool || {}).clubs || []).filter(function (c) { return (c.in_league || (c.played || 0) > 0) && isNum(c.strength); }).sort(function (a, b) { return b.strength - a.strength; }).slice(0, 8);
  if (!clubs.length) { box.innerHTML = FB.muted('The pooled fit is not available.'); return; }
  box.innerHTML = leadList(clubs.map(function (c) { return { who: FB.clubLink(c.team_id, c.team), sub: c.comp_name || '', v: num(c.strength, 2) }; }));
}
function drawNations(el, n) {
  var box = el.querySelector('#ov-nations');
  var t = ((n || {}).teams || []).slice(0, 8);
  if (!t.length) { box.innerHTML = FB.muted('No international fit yet.'); return; }
  FB.clubsIndex().then(function (ci) {
    if (!FB.alive(box)) return;
    var byName = {};
    ci.list.forEach(function (r) { if (r.national) byName[r.name] = r.id; });
    box.innerHTML = leadList(t.map(function (x) { return { rank: x.rank, who: FB.clubLink(byName[x.team], x.team), sub: x.confederation || '', v: num(x.strength, 2) }; }));
  });
}
function drawLast(el) {
  var last = FB.comps().filter(function (c) { return c.ok && FB.isLastEdition(c); });
  var box = el.querySelector('#ov-last');
  if (!last.length) { box.innerHTML = FB.muted('Every competition followed has an edition in progress.'); return; }
  box.innerHTML = last.map(function (c) {
    var won = c.winner && c.winner.team ? c.winner : null;
    return '<a class="fb-ov-lastc" href="' + esc(FB.href.comp(c.slug)) + '"><span class="qk-kicker">' + esc(FB.currentSeason(c).season) + '</span><b>' + esc(c.name) + '</b>' +
      '<span class="fb-ov-won">' + (won ? FB.crest(won.tid, won.team, 'sm') + esc(won.team) : '<span class="qk-muted">last edition</span>') + '</span></a>';
  }).join('');
}

})(window.FB);
