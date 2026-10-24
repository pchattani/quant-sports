/* The Quant Footballer — Overview (#/): every competition at once, on kit v4 "Broadcast" (dark only). The Rink overview
 * (docs/rink/assets/js/rk-overview.js) is the reference page; docs/_design/MIGRATION_V4.md has the steps.
 *
 *   ticker         the black ticker: today's live, coming and finished matches by competition
 *   intro          what the site covers and how to use it: three quick links (Matches, Competitions, Players), then
 *                  the big leagues and "All 69" as chips
 *   this week      "This week in football" (hub.json digest, scripts/build_site_all.py build_digest): the stage of the
 *                  big leagues, then the top lines as black tiles: the biggest title-chance mover (history.json), the
 *                  upset of the week and our record (only from forecast_log.json: the chance frozen before kick-off),
 *                  the team of the week, the biggest races' favourites, the other matches that matter
 *   the big one    the match that matters most on the shared significance rule (digest.featured: competition tier,
 *                  stage, the title stakes in our simulations, the hour, closeness a small bonus) as the diagonal split
 *                  hero, home first, labelled "Live now", "Tonight" (17:00 or later today, the reader's time), "Today",
 *                  "Tomorrow" or the weekday; nothing big on: the races lead instead
 *   N matches.     game cards for one day (our home / draw / away chance before kick-off, the score and xG after),
 *   Our calls.     each with a line on why, big matches first (digest.featured), then how big and close; the day and the competition
 *                  family are pickers. No market anywhere on this page.
 *   who's hot      the black power list (QK.band + QK.hotRow): goals, assists, rating, finishing, the strongest club
 *   we say it      "We say it. Then we check it." (QK.howSure from data/calibration.json, the walk-forward backtest)
 *                  beside "Who's for real?" (QKC.quadrant: xG share against points per game, one league at a time)
 *   what's that    "What's that number?": three things to know, the third linking the Model page
 *   title race     "Who wins the league?": our title chances for one big league in club colours (ours only), beside
 *                  the race run by run (forecast lines with end labels); then every open race's favourite
 *   leaders        goals against xG across competitions; the strongest clubs on the pooled scale; national teams
 *   leagues        the leagues at a glance: progress, leader, our favourite, top scorer
 *
 * Football has no live model: a match in play keeps our pre-match chance, labelled "our pre-game chance" (FB.toGame
 * sets pre_only), as on the Home page and the ticker.
 *
 * Reads competitions.json (FB.INDEX), clubs_index.json (names, colours), hub.json, lab/leaders.json, the big
 * leagues' probs.json, strength.json, teams.json and history.json, pool.json, nations.json and calibration.json; each
 * block degrades on its own. While a match is live, hub.json is re-read every minute. A match a cached snapshot still
 * marks live 12 hours after kick-off is not counted as live (FB.staleLive). */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, pct = FB.pct, num = FB.num;

var BIG = ['premier-league', 'la-liga', 'serie-a', 'bundesliga', 'ligue-1'];
var FAM_CHIPS = [['all', 'All'], ['league', 'Leagues'], ['cup', 'Continental'], ['domestic', 'National cups'], ['super', 'Super cups'], ['international', 'National teams']];
var view = { fam: 'all', day: null, race: 'premier-league', real: 'premier-league' };
var NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
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
/* How much a match is worth watching: live first, then close calls in the biggest competitions, then soonest. */
function watchRank(m) {
  var g = FB.toGame(m, m.comp);
  var s = QK.watchScore(g);
  if (s < -1e8) s = 0;
  return s + (PROM[m.comp] || 0) + (isLive(m) ? 10 : 0) - (m.status === 'postponed' || m.status === 'cancelled' ? 50 : 0);
}

FB.route('overview', function (el) {
  var comps = FB.comps();
  var nOk = comps.filter(function (c) { return c.ok; }).length;
  el.innerHTML =
    '<div class="qk-ticker fb-ov-ticker" id="ov-ticker" aria-label="Scores and our chances" hidden></div>' +
    introHTML() +
    '<div class="fb-ov-quick">' + BIG.concat(['champions-league', 'brasileirao', 'mls', 'liga-argentina', 'libertadores']).filter(function (s) { return FB.comp(s) && FB.comp(s).ok; }).map(function (s) {
      return '<a class="qk-chip" href="' + esc(FB.href.comp(s)) + '">' + esc(FB.compName(s, true)) + '</a>';
    }).join('') + '<a class="qk-chip" href="#/competitions">All ' + nOk + ' →</a></div>' +
    '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: 'This week in football', title: '<span id="ov-wk">The week so far</span>', html: true, sub: '<span id="ov-stage"></span>' }) +
      '<div id="ov-week">' + QK.skeleton('lines', 2) + '</div><div id="ov-feat" class="ql-feat"></div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch', title: '<span id="ov-gh">Today</span>', html: true,
        sub: '<span id="ov-day-sub">Our chance for each side, with a line on why it’s worth your time. Kick-off in your time zone; during a match the card keeps our pre-match chance.</span>',
        actions: '<span id="ov-days"></span><a class="qk-more" href="#/matches">Every match</a>' }) +
      '<div class="qk-chips scroll" id="ov-fam" role="group" aria-label="Competition family">' + FAM_CHIPS.map(function (f) {
        return '<button class="qk-chip" type="button" data-value="' + f[0] + '" aria-pressed="' + (f[0] === view.fam) + '">' + esc(f[1]) + ' <span class="n" data-n="' + f[0] + '"></span></button>';
      }).join('') + '</div>' +
      '<div id="ov-cards" class="qk-watch fb-mt">' + QK.skeleton('card', 3) + '</div>' +
      '<div id="ov-more" class="fb-cap"></div></section>' +
    '<div id="ov-hot">' + QK.skeleton('lines', 2) + '</div>' +
    '<section class="qk-section qk-g75 fb-ov-sure"><div><div id="ov-sure-h"></div><div id="ov-sure">' + QK.skeleton('chart', 1) + '</div></div>' +
      '<div class="fb-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Clubs top-left are winning more than their chances suggest; bottom-right, the reverse. Early-season luck, or something real?' }) +
      '<div id="ov-real-pick" class="fb-ov-pick"></div>' +
      '<div class="qk-card"><div class="qk-card-body"><div id="ov-real" class="qk-chart" role="img" aria-label="Share of expected goals against points per game, one league"></div><p class="qk-caption" id="ov-real-cap"></p></div></div></div></section>' +
    '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against others in the same role (centre-backs with centre-backs, strikers with strikers): 90th means better than 90 in 100.',
      'Every forecast is checked against what happened. <a class="qk-link" href="#/model/calibration">The record is on the Model page.</a>'] }) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: '<span id="ov-race-t">Who wins the league?</span>', html: true, sub: '<span id="ov-race-lede">Our chances from 30,000 simulated seasons.</span>',
        actions: '<span id="ov-race-pick"></span>' }) +
      FB.grid(
        FB.card('<span id="ov-tr-h">Title chances</span>', 'Our chance of winning the league, in club colours.', '<div id="ov-title">' + QK.skeleton('lines', 6) + '</div>', { span: 6, foot: '<span>From 30,000 simulated seasons</span><a id="ov-tr-more" href="#/competitions">Every season forecast →</a>' }) +
        FB.card('The race, run by run', 'Our title chance after each hourly model run, for the top five.', FB.chartBox('ov-race', 340, 'Title chances over time'), { span: 6 })
      ) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Season simulations', title: 'Every race, one favourite each', sub: 'Each open competition’s favourite and our chance that it wins it.', actions: '<a class="qk-more" href="#/competitions">Every competition</a>' }) +
      FB.card('Favourites', 'Our chance that each open competition’s favourite wins it.', '<div id="ov-races"></div>', { foot: '<span>Up to fourteen open races</span><a href="#/competitions">Every competition →</a>' }) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Leaderboards', title: 'Goals, chances and the strongest sides', sub: 'Across every competition this season, and every club and national team on one scale.', actions: '<a class="qk-more" href="#/players/leaders">Players</a>' }) +
      FB.grid(
        FB.card('Goals against expected', 'The leading scorers across every competition: goals scored and the expected goals (xG) of their shots.', FB.chartBox('ov-goals', 360, 'Goals and xG of the top scorers') +
          QK.explain('<b>What’s that number?</b> <b>xG</b> is how many goals an average finisher would score from the same shots. Well above it is great finishing or good luck; one season rarely tells the two apart.'), { span: 6 }) +
        '<div class="qk-span-3">' + FB.card('Strongest clubs', 'Our rating: expected points a game against an average side.', '<div id="ov-pool"></div>', { flush: true, foot: '<span></span><a href="#/clubs">All clubs →</a>' }) + '</div>' +
        '<div class="qk-span-3">' + FB.card('Strongest national teams', 'Our international rating, the same scale.', '<div id="ov-nations"></div>', { flush: true, foot: '<span></span><a href="#/clubs/nations">All national teams →</a>' }) + '</div>'
      ) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Leagues', title: 'Every league at a glance', sub: 'How far each league has gone, who leads, our title favourite and the top scorer.', actions: '<a class="qk-more" href="#/competitions">Competitions</a>' }) +
      FB.card('', '', '<div id="ov-leagues"></div>', { flush: true }) + '</section>' +
    '';

  QK.chips(el.querySelector('#ov-fam'), function (vals) { view.fam = vals[0] || 'all'; drawCards(el, HUB); });

  var HUB = null, POOL = null;
  var hubP = FB.load('hub.json');
  var poolP = FB.load('pool.json');
  var p = Promise.all([hubP, poolP]).then(function (arr) {
    if (!FB.alive(el)) return;
    HUB = arr[0] || { days: {} };
    POOL = arr[1];
    FORM = formMap(POOL);
    drawWeek(el, HUB);
    drawCards(el, HUB);
    drawTicker(el, HUB);
    drawLeaders(el, HUB);
    drawPool(el, POOL);
    FB.load('lab/leaders.json').then(function (board) { if (FB.alive(el)) drawHot(el, board, HUB, POOL); });
  });
  drawSure(el);
  drawRaces(el);
  drawTitle(el);
  drawReal(el);
  drawLeagues(el);
  FB.load('nations.json').then(function (n) { if (FB.alive(el)) drawNations(el, n); });

  /* live: re-read the scoreboard every minute while anything is in play or about to start */
  FB.interval(function () {
    var soon = allHub(HUB).some(function (m) { var t = FB.parseDate(m.date); return isLive(m) || (m.status !== 'finished' && t && Math.abs(t - Date.now()) < 15 * 60000); });
    if (!soon) return;
    FB.reload('hub.json').then(function (h) { if (!FB.alive(el) || !h) return; HUB = h; FB.hubLive(h); drawCards(el, HUB); drawTicker(el, HUB); });
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

/* ── the landing top: the intro band, "This week in football" (hub.json digest: oddsmarkets/common/digest.py, built
   by scripts/build_site_all.py build_digest) and the match that matters most (digest.featured: the shared
   significance rule, oddsmarkets/common/featured.py). The page clock is QK.now(), so ?asof= previews agree. */
function nowDay() { return FB.localDay(new Date(QK.now())); }
/* "Live now" | "Tonight" | "Today" | "Tomorrow" | the weekday | the date, in the reader's own time. */
function whenLabel(m) {
  if (!m) return '';
  if (isLive(m)) return 'Live now';
  if (m.status === 'finished') return 'Full time';
  var d = FB.parseDate(m.date), now = new Date(QK.now());
  if (!d) return '';
  var d0 = function (x) { var y = new Date(x.getTime()); y.setHours(0, 0, 0, 0); return y.getTime(); };
  var n = Math.round((d0(d) - d0(now)) / 864e5);
  if (n === 0) return d.getHours() >= 17 ? 'Tonight' : 'Today';
  if (n === 1) return 'Tomorrow';
  if (n > 1 && n < 7) return d.toLocaleDateString('en-GB', { weekday: 'long' });
  return QK.fmt.date(m.date);
}
function dayOf(iso) { return QK.fmt.date(String(iso || '').length === 10 ? iso + 'T12:00:00' : iso); }
function introHTML() {
  var n = FB.comps().filter(function (x) { return x.ok; }).length, live = FB.comps().filter(inSeason).length;
  var links = [{ label: 'Matches', sub: 'Every match, our chance', href: '#/matches' }, { label: 'Competitions', sub: 'Tables and title races', href: '#/competitions' }, { label: 'Players', sub: 'Leaders and percentiles', href: '#/players' }];
  return '<section class="ql-intro" aria-label="About this site"><div class="ql-intro-l"><div class="qk-greet-date">Football · ' + esc(String(live)) + ' competitions in season</div>' +
    '<h1>Every match in ' + esc(String(n)) + ' competitions, by the numbers.</h1>' +
    '<p>Our chance for today’s matches, who’s for real, and the title races from 30,000 simulated seasons, with a page for every club and player. Every number explained.</p></div>' +
    '<nav class="ql-links" aria-label="Start here">' + links.map(function (l) { return '<a href="' + esc(l.href) + '"><b>' + esc(l.label) + '</b><span>' + esc(l.sub) + '</span></a>'; }).join('') + '</nav></section>';
}
function hubById(h) {
  var by = {};
  allHub(h).concat((h || {}).upcoming || []).forEach(function (m) { if (m && m.id) by[String(m.id)] = m; });
  return by;
}
/* The match that matters most at the reader's clock: the first of digest.featured.today still to come or live,
   then .next (later this week), then .week; with none, null (the page leads with the races instead). */
function pickFeatured(h) {
  var F = ((h || {}).digest || {}).featured;
  if (!F) return null;
  var by = hubById(h), now = QK.now();
  var ok = function (f, hrs) {
    var m = f && by[String(f.id)];
    if (!m || m.status === 'finished' || m.status === 'postponed' || m.status === 'cancelled') return false;
    var t = FB.parseDate(m.date), hh = t ? (t - now) / 36e5 : null;
    if (hh === null) return false;
    return isLive(m) ? hh > -3 : hh > -0.25 && hh < hrs;
  };
  var T = (F.today || []).filter(function (f) { return ok(f, 24); });
  var N = (F.next || []).filter(function (f) { return ok(f, 24 * 7); });
  var f = T[0] || N[0] || (ok(F.week, 24 * 7) ? F.week : null);
  if (!f) return null;
  var rest = T.concat(N).filter(function (x) { return x !== f; }).map(function (x) { return by[String(x.id)]; });
  return { m: by[String(f.id)], f: f, later: !T.length, rest: rest };
}
function whyOf(f, m) {
  var lead = (f.why || []).join(' and ');
  var t = f.title, c = FB.comp(m.comp) || {};
  var sides = t ? [[m.home, t[0]], [m.away, t[1]]].filter(function (x) { return x[1] >= 0.01; }) : [];
  var nums = sides.length ? 'our chance to win ' + (c.short_name || c.name || 'it') + ': ' + sides.map(function (x) { return x[0] + ' ' + pct(x[1]); }).join(', ') : '';
  if (!lead && !nums) return '';
  return lead ? cap(lead) + (nums ? '; ' + nums : '') + '.' : cap(nums) + '.';
}
function drawWeek(el, h) {
  var dig = (h || {}).digest || {};
  var feat = pickFeatured(h);
  var T = [];
  var mv = dig.movers;
  if (mv && ((mv.up || []).length || (mv.down || []).length)) {
    var u0 = (mv.up || [])[0], d0 = (mv.down || [])[0], lead = u0 && (!d0 || Math.abs(u0.delta) >= Math.abs(d0.delta)) ? u0 : d0;
    var pts = function (x) { return (x.delta > 0 ? '+' : '−') + Math.abs(Math.round(x.delta * 100)) + ' pts'; };
    var other = lead === u0 ? d0 : u0;
    T.push({ label: 'Biggest mover', value: lead.name + ' ' + pts(lead), text: lead.name.length > 10, signal: true, href: lead.id ? FB.href.club(lead.id, { c: lead.comp }) : FB.href.comp(lead.comp, 'odds'),
      sub: (lead.delta > 0 ? 'Up' : 'Down') + ' to ' + pct(lead.to) + ' to win ' + (lead.league || '') + ' since ' + dayOf(lead.since) + '.' + (other ? ' ' + (other.delta > 0 ? 'Biggest rise' : 'Biggest fall') + ': ' + other.name + ' ' + pts(other) + '.' : '') });
  }
  var up = dig.upset;
  if (up) {
    var w = up.winner || {}, l = up.loser || {}, sc = up.side === 'home' ? up.hs + '–' + up.as : up.as + '–' + up.hs;
    T.push({ label: 'Upset of the week', value: (w.name || '') + ' ' + pct(up.p), text: String(w.name || '').length > 10, href: FB.href.match(up.comp, up.id),
      sub: (w.name || '') + ' beat ' + (l.name || '') + ' ' + sc + ' on ' + QK.fmt.date(up.start) + '. We gave them ' + pct(up.p) + ' before kick-off.' });
  }
  var hot = dig.hot;
  if (hot) T.push({ label: 'Team of the week', value: hot.name + ' ' + (hot.d ? 'W' + hot.w + ' D' + hot.d + (hot.l ? ' L' + hot.l : '') : hot.w + '–' + hot.l), text: String(hot.name).length > 10, href: isNum(hot.key) ? FB.href.club(hot.key) : null,
    sub: hot.w + ' wins' + (hot.d ? ', ' + hot.d + ' draw' + (hot.d === 1 ? '' : 's') : '') + ' in ' + hot.gp + ' matches this week, ' + (hot.margin >= 0 ? '+' : '−') + Math.abs(hot.margin) + ' goal difference.' });
  var r = dig.record;
  if (r) T.push({ label: 'Our record this week', value: r.won + ' of ' + r.n, href: '#/model/calibration',
    sub: 'Our favourites won ' + r.won + ' of ' + r.n + '; we expected ' + num(r.expected, 0) + '.' + (r.draws ? ' ' + r.draws + ' ended level.' : '') });
  /* fewer than four lines: the biggest races' favourites fill in */
  ['champions-league'].concat(BIG).forEach(function (s) {
    if (T.length >= 4) return;
    var c = FB.comp(s);
    if (!c || !inSeason(c) || !c.favourite || !isNum(c.p_favourite)) return;
    T.push({ label: (c.short_name || c.name) + ' favourite', value: c.favourite + ' ' + pct(c.p_favourite), text: String(c.favourite).length > 10, href: FB.href.comp(s, 'odds'),
      sub: 'Our chance to ' + (c.kind === 'league' ? 'win the league' : 'lift the trophy') + ', from 30,000 simulated seasons.' });
  });
  var rest = feat ? feat.rest.filter(Boolean).slice(0, 2) : [];
  if (rest.length) T.push({ label: 'Also worth a look', value: rest.map(function (m) { return FB.clubCode(m.home, m.away) + '–' + FB.clubCode(m.away, m.home); }).join(' · '), text: rest.length > 1, href: '#/matches',
    sub: rest.map(function (m) { return whenLabel(m) + (isLive(m) ? '' : ' ' + QK.fmt.time(m.date)) + ': ' + m.home + ' v ' + m.away + ' (' + (m.comp_name || '') + ')'; }).join('. ') + '.' });
  var box = el.querySelector('#ov-week');
  if (box) box.innerHTML = T.length ? QK.stats(T) : '';
  if (T.length >= 3) FB.set('ov-wk', 'The week in ' + NUMW[T.length].toLowerCase() + ' lines');
  FB.set('ov-stage', esc(stageLine(dig.stage)));
  drawFeature(el, h, feat);
}
function stageLine(st) {
  if (!st || !(st.big || []).length) return '';
  var lg = st.big.filter(function (b) { return b.comp !== 'champions-league' && b.round > 0; });
  var ucl = st.big.filter(function (b) { return b.comp === 'champions-league'; })[0];
  var parts = lg.map(function (b) { return b.name + ' ' + b.round + ' of ' + b.rounds; });
  var s = parts.length ? 'Rounds played: ' + parts.join(', ') + '.' : '';
  if (ucl && ucl.rounds) s += ' The Champions League league phase is ' + ucl.round + ' of ' + ucl.rounds + ' matchdays in' + (ucl.next ? '; next on ' + QK.fmt.date(ucl.next) : '') + '.';
  return s.trim();
}
function drawFeature(el, h, feat) {
  var box = el.querySelector('#ov-feat');
  if (!box) return;
  if (feat && feat.m) {
    var m = feat.m, g = FB.heroGame(FB.toGame(m, m.comp)), c = FB.comp(m.comp) || {};
    var lab = whenLabel(m), why = whyOf(feat.f, m);
    var f = isNum(g.p_home) ? [g.p_home, isNum(g.p_draw) ? g.p_draw : 0, isNum(g.p_away) ? g.p_away : 1 - g.p_home - (g.p_draw || 0)] : null;
    var sure = '';
    if (f && !isLive(m)) {
      var fav = f[0] >= f[2] ? m.home : m.away, pf = Math.max(f[0], f[2]), miss = Math.max(1, Math.round(10 * (1 - pf)));
      sure = ' <b>How sure are we?</b> ' + pct(pf) + ' for ' + esc(fav) + ' means a match like this goes another way about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.';
    }
    box.innerHTML = QK.splitHero(g, { homeFirst: true, noun: 'match', kicker: (c.name || FB.compName(m.comp)) + (g.note ? ' · ' + g.note : ''),
      tag: lab + (feat.later ? ' · The big one this week' : ' · The one to watch'), note: why ? '<b>Why this match?</b> ' + esc(why) + sure : (sure ? sure.slice(1) : undefined) });
    return;
  }
  /* nothing big on: lead with the races */
  var rows = FB.comps().filter(function (x) { return inSeason(x) && x.favourite && isNum(x.p_favourite) && !x.complete && x.p_favourite < 0.995 && (PROM[x.slug] || 0) >= 9; })
    .sort(function (a, b) { return (PROM[b.slug] || 0) - (PROM[a.slug] || 0); }).slice(0, 6);
  box.innerHTML = rows.length ? '<div class="ql-race">' + QK.sectionHead({ kicker: 'No big match today', title: 'So here are the races', sub: 'The favourite in each of the biggest competitions, and our chance it wins.', tag: 'h3' }) +
    FB.chances(rows.map(function (x) { return { label: x.favourite, sub: x.short_name || x.name, p: x.p_favourite, href: FB.href.comp(x.slug, 'odds'), mark: { name: x.favourite } }; }), { max: 1, key: false }) + '</div>' : '';
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
  var t = nowDay();
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
  var rk = {}, sig = {};
  var F = (h || {}).digest && h.digest.featured;
  if (F) (F.today || []).concat(F.next || [], F.week ? [F.week] : []).forEach(function (f) { if (!(String(f.id) in sig)) sig[String(f.id)] = f.score; });
  list.forEach(function (m) { rk[m.id] = (String(m.id) in sig ? 100 + sig[String(m.id)] : 0) + watchRank(m); });
  /* live first, then the matches still to come (biggest first), then the results */
  var grp = function (m) { return isLive(m) ? 0 : m.status === 'finished' ? 2 : 1; };
  list.sort(function (a, b) { return (grp(a) - grp(b)) || (rk[b.id] - rk[a.id]) || String(a.date).localeCompare(String(b.date)); });
  var gh = el.querySelector('#ov-gh');
  var dayName = view.day === t ? 'today' : FB.relDay(view.day + 'T12:00:00');
  var shownN = Math.min(9, list.length);
  if (gh) gh.textContent = list.length ? (NUMW[shownN] || shownN) + ' match' + (shownN === 1 ? '' : 'es') + '. Our calls.' : (view.day === t ? 'Nothing on today' : 'Nothing on ' + dayName);
  var ds = el.querySelector('#ov-day-sub');
  if (ds) ds.textContent = (list.length > shownN ? 'Our ' + NUMW[shownN].toLowerCase() + ' picks of ' + list.length + ' ' + (view.day === t ? 'today' : dayName) + '. ' : (view.day === t ? '' : cap(dayName) + '. ')) +
    'Our chance for each side, with a line on why it’s worth your time. Kick-off in your time zone; during a match the card keeps our pre-match chance.';
  var box = el.querySelector('#ov-cards');
  if (!box) return;
  if (!list.length) { box.innerHTML = '<div style="grid-column:1/-1">' + FB.empty('No matches', view.fam === 'all' ? 'Nothing scheduled across the competitions followed on this day.' : 'Nothing from this family on this day.') + '</div>'; FB.set('ov-more', ''); return; }
  var LIM = 9;
  box.innerHTML = list.slice(0, LIM).map(function (m) { return FB.matchCard(m, m.comp, extraFor(m, true)); }).join('');
  var more = el.querySelector('#ov-more');
  if (more) more.innerHTML = list.length > LIM ? '<a href="' + esc(FB.href.matches({ d: view.day, f: view.fam === 'all' ? null : view.fam })) + '">See all ' + list.length + ' matches on this day →</a>' : '';
}
function cap(x) { x = String(x || ''); return x.charAt(0).toUpperCase() + x.slice(1); }
function shiftDay(k, n) { var d = FB.parseDate(k + 'T12:00:00'); d.setDate(d.getDate() + n); return FB.localDay(d); }

/* ── the ticker: live first, then today's coming matches, then today's results (kit QK.ticker by league) */
function drawTicker(el, h) {
  var box = el.querySelector('#ov-ticker');
  if (!box) return;
  var t = nowDay();
  var list = allHub(h).filter(function (m) { return isLive(m) || FB.localDay(m.date) === t; });
  if (!list.length) { box.hidden = true; return; }
  var rank = {};
  FB.comps().forEach(function (c, i) { rank[c.slug] = i; });
  list.sort(function (a, b) { return (rank[a.comp] === undefined ? 999 : rank[a.comp]) - (rank[b.comp] === undefined ? 999 : rank[b.comp]) || String(a.date).localeCompare(String(b.date)); });
  var games = list.slice(0, 40).map(function (m) { return FB.toGame(m, m.comp); });
  box.innerHTML = QK.ticker(games, { group: 'league', max: 40, pill: false });
  box.hidden = false;
}

/* ── who's hot: the black power list (QK.band + QK.hotRow), one name each, across every competition (lab/leaders.json;
   hub.json's lists when it is missing) */
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
  if (g0) items.push({ sport: 'football', _where: g0.team || g0.comp_name || '', title: g0 === top(goals) ? 'Most goals' : 'Goals', name: g0.name, value: g0.value, unit: 'goals' + (L ? ' in all competitions' : ''), href: FB.href.player(g0.id),
    next: nextOf(goals, g0),
    expl: isNum(g0.xg) ? whereOf(g0) + '. From shots worth ' + num(g0.xg, 1) + ' expected goals: ' + (g0.value - g0.xg >= 2 ? 'finishing well above an average shooter.' : g0.value - g0.xg <= -2 ? 'unlucky or wasteful in front of goal.' : 'about what the chances were worth.') : whereOf(g0) + '.' });
  if (a0) items.push({ sport: 'football', _where: a0.team || a0.comp_name || '', title: a0 === top(assists) ? 'Most assists' : 'Assists', name: a0.name, value: a0.value, unit: 'assists', href: FB.href.player(a0.id),
    next: nextOf(assists, a0),
    expl: behind(assists, a0) + (isNum(a0.xa) ? whereOf(a0) + '. Passes worth ' + num(a0.xa, 1) + ' expected assists: the chances created, whatever the finish.' : whereOf(a0) + '.') });
  if (r0) items.push({ sport: 'football', _where: r0.team || r0.comp_name || '', title: r0 === top(rating) ? 'Best rating' : 'Rating', name: r0.name, value: num(r0.value, 2), unit: 'average match rating', href: FB.href.player(r0.id),
    next: nextOf(rating, r0, function (v) { return num(v, 2); }),
    expl: behind(rating, r0, function (v) { return num(v, 2); }) + 'Out of 10, weighted by minutes' + (isNum(r0.minutes) ? ' over ' + FB.int(r0.minutes) + ' minutes' : '') + '. A 7 is a good game; above 8 is rare over a season.' });
  var fin = goals.filter(function (r) { return isNum(r.xg) && r.value >= 5 && !used[String(r.id)]; }).map(function (r) { return [r.value - r.xg, r]; }).sort(function (a, b) { return b[0] - a[0]; });
  if (fin[0] && fin[0][0] > 0) items.push({ sport: 'football', _where: fin[0][1].team || fin[0][1].comp_name || '', title: 'Hottest finisher', name: fin[0][1].name, value: '+' + num(fin[0][0], 1), unit: 'goals above expected', href: FB.href.player(fin[0][1].id),
    next: fin[1] ? { name: fin[1][1].name, value: '+' + num(fin[1][0], 1) } : null,
    expl: fin[0][1].value + ' goals from ' + num(fin[0][1].xg, 1) + ' xG. Hot streaks like this rarely last: finishing above xG mostly evens out.' });
  var clubs = ((pool || {}).clubs || []).filter(function (c) { return (c.in_league || (c.played || 0) > 0) && isNum(c.strength); }).sort(function (a, b) { return b.strength - a.strength; });
  if (clubs[0]) items.push({ sport: 'football', _where: clubs[0].comp_name || '', title: 'Strongest club', name: clubs[0].team, value: num(clubs[0].strength, 2), unit: 'points a game, our rating', href: clubs[0].team_id ? FB.href.club(clubs[0].team_id) : null,
    next: clubs[1] ? { name: clubs[1].team, value: num(clubs[1].strength, 2) } : null,
    expl: 'What we’d expect it to take from a game against an average side anywhere. ' + (clubs[0].comp_name ? clubs[0].comp_name + '.' : '') });
  items.forEach(function (x) { x.kicker = 'Football' + (x._where ? ' · ' + x._where : ''); });
  box.innerHTML = QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaders, board by board', sub: 'One name on each board, across every competition this season, and a line on what the number means.',
    actions: '<a class="qk-more" href="#/players/leaders">Every leader</a>' }) + (items.length ? QK.hotRow(items) : FB.empty('No leaders yet', 'The leaders appear once the season’s first matches are in.')));
}

/* ── "We say it. Then we check it.": the match model's walk-forward record from data/calibration.json (QK.howSure: three
   big numbers over the we-said / it-happened bars); the full record is on the Model page */
function calibOf(j) {
  if (!j) return null;
  return QK.calib.find(j) || QK.calib.find(j.match_model) || QK.calib.find(j.overall) || QK.calib.find(j.model);
}
FB.calibOf = calibOf;
function drawSure(el) {
  FB.load('calibration.json').then(function (cj) {
    var box = el.querySelector('#ov-sure'), hd = el.querySelector('#ov-sure-h');
    if (!box || !FB.alive(el)) return;
    var cb = calibOf(cj);
    if (!cb || !cb.bins.length) { box.innerHTML = ''; hd.innerHTML = ''; var sec = el.querySelector('.fb-ov-sure'); if (sec) sec.classList.add('solo'); return; }
    var subj = (cj && cj.subject) || 'the home side';
    var nL = cj && Array.isArray(cj.leagues) ? cj.leagues.length : 0;
    hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.',
      sub: 'Every match in our backtest' + (nL ? ' across ' + nL + ' leagues' : '') + ', grouped by the chance we gave ' + subj + ' to win. When the two bars match, our numbers mean what they say.',
      actions: '<a class="qk-more" href="#/model/calibration">The full record</a>' });
    QK.howSure(box, { bins: cb.bins, brier: cb.brier, n: cb.n, league: nL ? nL + ' leagues' : 'Football', span: cj && cj.span, subject: subj, unit: (cj && cj.unit) || 'matches' });
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
/* ── "Who wins the league?": one big league at a time, our title chances as club-colour bars (QK.chances: a club with no
   colour in clubs_index.json is ours in blue) beside the race run by run; the league seg drives both. Ours only. */
function teamIds(teams) {
  var out = {};
  var t = (teams || {}).teams || {};
  Object.keys(t).forEach(function (n) { if (t[n] && t[n].team_id) out[n] = t[n].team_id; });
  return out;
}
function drawTitle(el) {
  var avail = BIG.filter(function (s) { var c = FB.comp(s); return c && inSeason(c) && FB.hasFile(s, 'probs'); });
  var pick = el.querySelector('#ov-race-pick');
  if (!avail.length) { FB.set('ov-title', FB.empty('No open title race', 'The big leagues are between seasons.')); FB.set('ov-race', ''); return; }
  if (avail.indexOf(view.race) < 0) view.race = avail[0];
  pick.innerHTML = FB.seg('ov-race-seg', avail.map(function (s) { return [s, FB.compName(s, true)]; }), view.race, 'League');
  FB.wireSeg(pick, 'ov-race-seg', function (v) { view.race = v; draw(); });
  function draw() {
    var slug = view.race;
    var c = FB.comp(slug) || {};
    var files = ['probs', 'teams'].concat(FB.hasFile(slug, 'history') ? ['history'] : []);
    FB.compFiles(slug, files).then(function (d) {
      if (!FB.alive(el) || view.race !== slug) return;
      var ids = teamIds(d.teams);
      var rows = ((d.probs || {}).teams || []).filter(function (r) { return isNum(r.p_title); }).map(function (r) {
        var tid = ids[r.team];
        return { label: r.team, p: r.p_title, href: tid ? FB.href.club(tid, { c: slug }) : null, mark: { name: r.team, logo: tid ? FB.crestUrl(tid) : null, colour: tid ? FB.clubColour(tid) : null }, color: tid ? FB.clubColour(tid) : null,
          sub: isNum(r.exp_pts) ? num(r.exp_pts, 0) + ' points expected' : '' };
      }).sort(function (a, b) { return b.p - a.p; });
      FB.set('ov-race-t', 'Who wins ' + (/^(la|ligue|serie|bundesliga)/i.test(c.short_name || c.name || '') ? '' : 'the ') + (c.short_name || c.name || 'the league') + '?');
      FB.set('ov-tr-h', esc(c.name || FB.compName(slug)) + ': title chances');
      var more = el.querySelector('#ov-tr-more'); if (more) more.setAttribute('href', FB.href.comp(slug, 'odds'));
      var r0 = rows[0];
      FB.set('ov-race-lede', r0 ? esc((r0.p < 0.2 ? 'Nobody’s better than 1 in 5. ' + r0.label + ' lead our board at ' + pct(r0.p) + '.' : r0.label + ' lead at ' + pct(r0.p) + (rows[1] ? ', ' + rows[1].label + ' next at ' + pct(rows[1].p) : '') + '.') + ' From 30,000 simulated seasons.') : 'Our chances from 30,000 simulated seasons.');
      FB.set('ov-title', rows.length ? QK.chances(rows, { limit: 8, key: false }) : FB.empty('No title chances yet', 'They arrive with the first simulation of the season.'));
      // the race, run by run
      var box = el.querySelector('#ov-race');
      if (!box) return;
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

/* ── "Who's for real?": each club's share of the expected goals in its matches (process) against its points per game
   (results), one league at a time (strength.json), the corners named (QKC.quadrant). Dashed lines: a 50% share and
   the league's average points per game. Club colours when clubs_index.json has them. */
function drawReal(el) {
  var avail = BIG.filter(function (s) { var c = FB.comp(s); return c && inSeason(c) && FB.hasFile(s, 'strength'); });
  var pick = el.querySelector('#ov-real-pick');
  if (!avail.length) { FB.set('ov-real', FB.empty('Not yet', 'The chart fills in after the first matches.')); return; }
  if (avail.indexOf(view.real) < 0) view.real = avail[0];
  pick.innerHTML = avail.length > 1 ? FB.seg('ov-real-seg', avail.map(function (s) { return [s, FB.compName(s, true)]; }), view.real, 'League') : '';
  FB.wireSeg(pick, 'ov-real-seg', function (v) { view.real = v; draw(); });
  function draw() {
    var slug = view.real;
    FB.compFiles(slug, ['strength', 'teams']).then(function (d) {
      if (!FB.alive(el) || view.real !== slug) return;
      var ids = teamIds(d.teams);
      var rows = ((d.strength || {}).rows || []).filter(function (r) { return r.played > 0 && isNum(r.xg_for) && isNum(r.xg_against) && r.xg_for + r.xg_against > 0 && isNum(r.ppg); });
      var box = el.querySelector('#ov-real');
      if (!box) return;
      if (rows.length < 6) { box.innerHTML = FB.empty('Not yet', 'The chart fills in after the first matches.'); FB.set('ov-real-cap', ''); return; }
      var pts = rows.map(function (r) {
        var tid = ids[r.team];
        return { x: 100 * r.xg_for / (r.xg_for + r.xg_against), y: r.ppg, name: r.team, label: FB.clubCode(r.team), color: tid ? FB.clubColour(tid) : null, href: tid ? FB.href.club(tid, { c: slug }) : null,
          sub: r.points + ' points in ' + r.played + ' · xG ' + num(r.xg_for, 1) + ' for, ' + num(r.xg_against, 1) + ' against' };
      });
      var avgY = pts.reduce(function (a, p) { return a + p.y; }, 0) / pts.length;
      var gps = rows.map(function (r) { return r.played; }), g0 = Math.min.apply(null, gps), g1 = Math.max.apply(null, gps);
      QKC.quadrant(box, { points: pts, xName: 'Share of expected goals in its matches (%)', yName: 'Points per game', refX: 50, refY: avgY,
        xFmt: function (v) { return Math.round(v) + '%'; }, yFmt: function (v) { return num(v, 1); }, label: FB.compName(slug) + ' clubs: share of expected goals against points per game' });
      FB.set('ov-real-cap', esc(FB.compName(slug) + ' ' + (FB.currentSeason(FB.comp(slug)).season || '') + ', ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' matches each. Dashed lines: a 50% share of the chances and the league’s average points per game (' + num(avgY, 2) + '). Tap a club for its page.'));
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
})(window.FB);
