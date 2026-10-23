/* The Quant Campus — Overview (#/<L>), on kit v3 "Matchday" (the Rink overview is the reference, MIGRATION_V3.md).
 *   the greeting hero with the game to watch (QK.featureCard); stat tiles: the title favourite (ours, in teal), the
 *     top-rated team with its uncertainty, AP No. 1, the next kick-off / tip-off or the live count (a past season: the
 *     champion);
 *   "What to watch": our picks from live, today's and upcoming games (or what's coming up, or the latest results), each
 *     card with a one-line reason and no market; "Who's hot" from the season leaders; "New here?" beside a "How sure
 *     are we?" teaser from <L>/calibration.json when it is there;
 *   who wins it all: our title chances (ours only: no market on the overview), power ratings with one standard error,
 *     AP poll v our ranking, the CFP picture (cfb) or bracketology / the bracket (basketball);
 *   leaders: value and the counting leaders, loaded after the page (value.json carries the names).
 * Reads index.json, <L>/<S>/season.json, <L>/<S>/cfp.json | bracket.json, <L>/history.json, <L>/calibration.json,
 * <L>/<S>/schedule.json (past seasons), then <L>/<S>/value.json (lazy). */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

function dataTable(cols, rows, label) {
  return '<details class="cc-data"><summary>' + esc(label || 'Show the numbers as a table') + '</summary>' + U.table(cols, rows, { maxHeight: 360 }) + '</details>';
}

function tiles(L, S, d, nSims) {
  var out = [], isCur = CC.isCur(L, S), info = CC.info(L), fb = CC.fb(L);
  var sim = d.sim, tit = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title); }).sort(function (a, b) { return sim[b].p_title - sim[a].p_title; });
  if (isCur && tit.length) {
    var fav = tit[0];
    out.push({ label: 'Title favourite', value: CC.tabbr(L, fav) + ' ' + CC.pct(sim[fav].p_title), signal: true, href: CC.teamHref(L, fav),
      sub: CC.tname(L, fav) + (nSims ? ' · from ' + QK.fmt.num(nSims) + ' simulated seasons' : ''), tip: 'Our chance of winning the national title: the share of simulated seasons the team wins it all' });
  } else if (d.champ) {
    out.push({ label: 'Champion', value: CC.tshort(L, d.champ), text: true, signal: true, href: CC.teamHref(L, d.champ, S), sub: CC.seasonLabel(L, S) });
  }
  var pw = d.power[0];
  if (pw) {
    var R = d.ratings[String(pw.team)] || {};
    out.push({ label: 'Top-rated team', value: CC.tabbr(L, pw.team) + ' ' + CC.signed(pw.rating, 1), href: CC.teamHref(L, pw.team, S),
      sub: (fb ? 'points better than an average FBS team' : 'points per 100 better than average D-I') + (isNum(R.se) ? ' · ± ' + CC.f(R.se, 1) : ''),
      tip: (fb ? 'Our rating: expected margin against an average FBS team on a neutral field' : 'Our rating: adjusted efficiency margin per 100 possessions') + (isNum(R.se) ? '; ± is one standard error' : '') });
  }
  var ap = d.ap[0];
  if (ap) out.push({ label: 'AP No. 1', value: CC.tshort(L, ap.team), text: true, href: CC.teamHref(L, ap.team, S),
    sub: (isNum(ap.first) && ap.first ? ap.first + ' first-place votes' : 'latest AP poll') + (d.rec[ap.team] ? ' · ' + d.rec[ap.team] : '') });
  if (isCur) {
    var live = (info.today || []).filter(function (g) { return g.status === 'in'; });
    var nx = (info.today || []).concat(info.next_games || []).filter(function (g) { return g.status === 'pre' && (CC.tba(g) || !(new Date(g.date).getTime() < Date.now() - 12 * 3600 * 1000)); }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); })[0];
    if (live.length) out.push({ label: 'Live now', value: String(live.length), unit: live.length > 1 ? 'games' : 'game', sub: live.slice(0, 3).map(function (g) { return CC.tabbr(L, g.away) + '–' + CC.tabbr(L, g.home); }).join(' · ') });
    else if (nx) out.push({ label: fb ? 'Next kick-off' : 'Next tip-off', value: CC.tba(nx) ? 'TBA' : QK.whenShort(nx.date), text: CC.tba(nx), href: CC.gameHref(L, nx.id, S),
      sub: CC.tabbr(L, nx.away) + ' @ ' + CC.tabbr(L, nx.home) + ' · ' + CC.date(CC.gameDate(nx)) });
    if (fb) {
      var po = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_cfp); }).sort(function (a, b) { return sim[b].p_cfp - sim[a].p_cfp; })[0];
      if (po && sim[po].p_cfp > 0) out.push({ label: 'Surest playoff team', value: CC.tabbr(L, po) + ' ' + CC.pct(sim[po].p_cfp), href: CC.teamHref(L, po), sub: 'our chance to make the 12-team playoff' });
    }
  }
  return U.stats(out);
}

/* The live, today's, upcoming and recent games of the level (a stale snapshot: a game still marked live or upcoming 12
   hours after its start is dropped, MIGRATION_V2.md). */
function gameLists(L, info) {
  var seen = {};
  var cut = Date.now() - 12 * 3600 * 1000;
  var fresh = function (g) { return g.status === 'post' || CC.tba(g) || !(new Date(g.date).getTime() < cut); };
  function take(list) { return (list || []).filter(function (g) { if (seen[g.id] || !fresh(g)) return false; seen[g.id] = 1; return true; }); }
  var live = take((info.today || []).filter(function (g) { return g.status === 'in'; }));
  var today = take(info.today);
  var next = take(info.next_games);
  var last = take(info.last_games);
  return { live: live, today: today, next: next, last: last };
}
/* Our picks: live first, then the games most worth watching (close calls, ranked or seeded teams, soonest). */
function pickScore(c, L) {
  var g = CC.game(c, L), s = QK.watchScore(g);
  if (s < -1e8) s = -50 - (new Date(c.date).getTime() - Date.now()) / 36e5 * 0.1;
  if (c.hr || c.ar || c.hseed || c.aseed) s += 6;
  if ((c.hr && c.ar) || (c.hseed && c.aseed)) s += 16;
  return s;
}
function watchBlock(L, S, G) {
  var fb = CC.fb(L);
  var pool = G.live.concat(G.today, G.next).filter(function (c) { return c.status !== 'post'; });
  var picks = pool.slice().sort(function (x, y) { return pickScore(y, L) - pickScore(x, L); }).slice(0, 6);
  var when = fb ? 'this week' : (new Date(QK.now()).getHours() >= 15 ? 'tonight' : 'today');
  var seg = '<div class="qk-seg" id="ov-when" role="group" aria-label="Games"><button type="button" aria-pressed="true" data-value="picks">Our picks</button><button type="button" aria-pressed="false" data-value="next"' + (pool.length ? '' : ' disabled') + '>Coming up</button><button type="button" aria-pressed="false" data-value="results"' + (G.last.length ? '' : ' disabled') + '>Latest results</button></div>';
  return { picks: picks, pool: pool, html: '<section class="qk-section cc-sec">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: '<span id="ov-gh">Games we’d pick</span>', html: true,
    sub: 'Our chance for each side, with a line on why it’s worth your time. ' + (fb ? 'Ranked teams carry their AP rank.' : 'Ranked and seeded teams carry their number.'), actions: seg }) + '<div id="ov-games"></div></section>' };
}
function drawWatch(el, L, W, G) {
  var NUM = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six'];
  var draw = function (w) {
    var list = w === 'results' ? G.last.slice(0, 6) : w === 'next' ? W.pool.slice().sort(function (x, y) { return String(x.date).localeCompare(String(y.date)); }).slice(0, 9) : (W.picks.length ? W.picks : G.last.slice(0, 6));
    var n = list.length;
    QK.$('#ov-gh', el).textContent = w === 'results' || !W.picks.length ? 'The latest results' : w === 'next' ? 'Coming up' : NUM[n] + ' game' + (n === 1 ? '' : 's') + ' we’d pick';
    QK.$('#ov-games', el).innerHTML = n ? '<div class="qk-watch">' + list.map(function (c) { return CC.card(c, L, { why: true }); }).join('') + '</div>' : QK.empty('No games right now', 'The next games appear here as soon as they are scheduled.');
  };
  draw('picks');
  QK.seg(QK.$('#ov-when', el), draw);
}

function pastGames(L, S, sched) {
  var PRI = { cfp: 0, ncaa: 0, bowl: 1, nit: 2, wbit: 2 };
  var g = ((sched && sched.games) || []).filter(function (c) { return c.status === 'post' && PRI[c.stype] !== undefined; });
  g.sort(function (a, b) { return PRI[a.stype] - PRI[b.stype] || String(b.date).localeCompare(String(a.date)); });
  if (!g.length) return '';
  return U.section('How it ended', 'The last postseason games of ' + esc(CC.seasonLabel(L, S)) + ', with our pre-game chance in each card’s foot.', '<div class="qk-watch">' + g.slice(0, 9).map(function (c) { return CC.card(c, L, { why: true }); }).join('') + '</div>',
    '<a class="qk-btn" href="' + esc(CC.href(L, 'games', null, S)) + '">All games</a>', 'Scoreboard');
}

CC.route('overview', function (el, p) {
  var L = p.L, S = p.S, isCur = CC.isCur(L, S), fb = CC.fb(L);
  var info = CC.info(L);
  var title = CC.LNAME[L] + ', by the numbers.';
  var sub0 = fb ? 'Our win chance for every FBS game, ratings with their uncertainty, conference, playoff and title chances from simulated seasons, and the players behind it.'
    : 'Our win chance for every Division I game, ratings with their uncertainty, tournament and title chances from simulated seasons, and the players behind it.';
  var actions = '<a class="qk-btn" href="' + esc(CC.href(L, 'games', null, S)) + '">All games</a><a class="qk-btn" href="' + esc(CC.href(L, 'standings', null, S)) + '">Standings</a>';
  el.innerHTML = U.head(title, esc(sub0), U.kicker(L, S), actions) + QK.skeleton('lines', 5);
  return Promise.all([CC.season(L, S), CC.load(CC.path(L, S, fb ? 'cfp.json' : 'bracket.json')),
    CC.load(CC.lpath(L, 'history.json')), isCur ? Promise.resolve(null) : CC.load(CC.path(L, S, 'schedule.json'))]).then(function (a) {
    if (!U.alive(el)) return;
    var season = CC.ok(a[0]) ? a[0] : null, post = CC.ok(a[1]) ? a[1] : null, hist = CC.ok(a[2]) ? a[2] : null;
    if (!season) { el.innerHTML = U.head(title, '', U.kicker(L, S)) + U.missing('This season', a[0]); return; }
    var sim = (season.sim && season.sim.teams) || {}, ratings = season.ratings || {};
    var nSims = season.sim && isNum(season.sim.n_sims) ? season.sim.n_sims : null;
    var power = (season.power || []).filter(function (r) { return r && r.team !== undefined; });
    if (!power.length) power = Object.keys(ratings).filter(function (t) { return isNum(ratings[t].rating); }).sort(function (x, y) { return ratings[y].rating - ratings[x].rating; }).map(function (t, i) { return { rank: i + 1, team: t, rating: ratings[t].rating }; });
    var ap = ((season.polls || {}).ap || []);
    var rec = {};
    Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { rec[String(r.team)] = CC.record(r.w, r.l); }); });
    var champ = null;
    ((hist && hist.champions) || []).forEach(function (c) { if (Number(c.season) === Number(S)) champ = String(c.team); });
    if (!champ && post && post.actual && post.actual.champion) champ = String(post.actual.champion);
    if (!champ && post && post.actual) {
      var fin = ((post.actual.games || (post.actual.bracket && post.actual.bracket.games)) || []).filter(function (g) { return /championship|^final$/i.test(String(g.round || '')) && (g.winner || CC.status(g) === 'final'); })[0];
      if (fin) champ = String(fin.winner || (fin.hs > fin.as ? fin.home : fin.away));
    }
    var d = { sim: sim, ratings: ratings, power: power, ap: ap, rec: rec, champ: champ };
    /* the builder's headline ("Week 8 · Ohio State lead the title chances at 18%") without its date part */
    var hl = isCur ? CC.copy(info.headline || '').replace(/^[^·]*·\s*/, '') : (champ ? CC.tname(L, champ) + ' won the title' : '');
    var G = isCur ? gameLists(L, info) : { live: [], today: [], next: [], last: [] };
    var W = isCur ? watchBlock(L, S, G) : null;
    var feat = W && W.picks.length ? CC.game(W.picks[0], L) : null;
    if (feat) { feat.home.record = CC.rec(L, S, W.picks[0].home); feat.away.record = CC.rec(L, S, W.picks[0].away); }
    var evening = new Date(QK.now()).getHours() >= 15;
    var html = QK.greeting({ date: U.kicker(L, S),
      title: isCur ? esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in ' + esc(fb ? 'college football' : L === 'mbb' ? 'men’s college basketball' : 'women’s college basketball') + ' ' + (fb ? 'this week' : evening ? 'tonight' : 'today') + '.'
        : esc(CC.LNAME[L] + ' ' + CC.seasonLabel(L, S)) + ', ' + QK.mark('looking back') + '.',
      lede: (hl ? hl.replace(/\.?$/, '. ') : '') + sub0,
      ctas: [{ label: 'All games', href: CC.href(L, 'games', null, S) }, { label: 'Standings', href: CC.href(L, 'standings', null, S), ghost: true }],
      side: feat ? QK.featureCard(feat, { scribble: feat.status === 'live' ? 'Live now!' : 'Our pick ' + (fb ? 'this week' : evening ? 'tonight' : 'today') + '!' }) : '' }) +
      '<div style="margin-top:var(--sp-10)">' + tiles(L, S, d, nSims) + '</div>';
    html += isCur ? W.html : pastGames(L, S, a[3]);
    html += '<div id="ov-hot"></div>';
    html += '<section class="qk-section qk-gside" id="ov-new"><div id="ov-sure"></div><div>' + QK.newHere({ items: [QK.NEW_HERE[0], QK.NEW_HERE[1], 'Every forecast is checked against what happened. <a class="qk-link" href="' + esc(CC.href(L, 'model', null, null, 'tab=calibration')) + '">The record is on the Model page.</a>'] }) + '</div></section>';
    // title chances: ours only (no market on the overview)
    var titleRows = (isCur ? (info.title_odds || []) : []).filter(function (r) { return isNum(r.p); }).slice(0, 12);
    if (!titleRows.length) titleRows = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title) && sim[t].p_title > 0; }).sort(function (x, y) { return sim[y].p_title - sim[x].p_title; }).slice(0, 12).map(function (t) { return { team: t, p: sim[t].p_title }; });
    var top = power.slice(0, 25);
    var grid = '<div class="qk-grid cc-grid">';
    if (titleRows.length) grid += '<div class="qk-span-5">' + U.card('National title chances', 'Our chance of winning it all' + (nSims ? ', from ' + QK.fmt.num(nSims) + ' simulated seasons' : '') + '.',
      '<div id="ov-title"></div>', { foot: '<span>Top ' + titleRows.length + '</span>' + U.link(CC.href(L, 'standings', null, S, fb ? 'tab=playoff' : 'tab=bracket'), fb ? 'The playoff picture' : 'The bracket') }) + '</div>';
    if (top.length) grid += '<div class="qk-span-7">' + U.card('Power ratings', (fb ? 'Points better than an average FBS team on a neutral field' : 'Adjusted efficiency margin per 100 possessions') + '; whiskers ± one standard error.',
      U.chart('ov-power', Math.max(320, top.length * 22 + 30), 'Power ratings, top 25') +
      dataTable(['#', 'Team', { label: 'Rating', align: 'right' }, { label: '±', align: 'right' }, { label: 'Record', align: 'right' }], top.map(function (r) { var R = ratings[String(r.team)] || {}; return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, { v: r.rating, html: CC.signed(r.rating, 1) }, CC.f(R.se, 1), rec[String(r.team)] || '—']; }))) + '</div>';
    grid += '</div><div class="qk-grid cc-grid">';
    if (ap.length) {
      var mrank = {}; power.forEach(function (r, i) { mrank[String(r.team)] = r.rank || i + 1; });
      var pts = ap.slice(0, 25).filter(function (r) { return isNum(mrank[String(r.team)]); });
      grid += '<div class="qk-span-6">' + U.card('AP poll v our ranking', 'Across: AP rank; down: our rank (1 at the top). Above the line, we rank the team higher than the voters do.', U.chart('ov-ap', 340, 'AP rank against our rank') +
        dataTable(['AP', 'Team', { label: 'Prev', align: 'right' }, { label: 'Ours', align: 'right' }, { label: 'Record', align: 'right' }], ap.slice(0, 25).map(function (r) { return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, isNum(r.prev) ? r.prev : '—', isNum(mrank[String(r.team)]) ? mrank[String(r.team)] : '—', rec[String(r.team)] || '—']; }))) + '</div>';
      d.apPts = pts; d.mrank = mrank;
    }
    grid += '<div class="qk-span-' + (ap.length ? 6 : 12) + '" id="ov-post"></div></div>';
    html += U.section(isCur ? 'Who wins it all' : 'The season in numbers', isCur ? 'Our chances from simulating the rest of the season, the ratings behind them and how they compare with the polls.' : '', grid, '', isCur ? 'Season simulation' : 'Season');
    html += '<div id="ov-leaders"></div>';
    el.innerHTML = html;
    U.wire(el);
    if (isCur) drawWatch(el, L, W, G);
    howSureTeaser(L, QK.$('#ov-sure', el));
    if (titleRows.length) QK.$('#ov-title', el).innerHTML = QK.chances(titleRows.map(function (r) { return { label: CC.tshort(L, r.team), p: r.p, href: CC.teamHref(L, r.team, S), mark: U.mark(L, r.team) }; }), { key: false }) +
      QK.note('Even the favourite misses most seasons: ' + CC.pct(titleRows[0].p, 0) + ' means about ' + Math.max(1, Math.round(10 * (1 - titleRows[0].p))) + ' seasons in 10 end without the title.');
    if (top.length) QKC.bar('#ov-power', { cats: top.map(function (r) { return CC.tshort(L, r.team); }), horizontal: true, fmt: function (v) { return CC.signed(v, 1); },
      series: [{ name: 'Rating', data: top.map(function (r) { return r.rating; }), lo: top.map(function (r) { var R = ratings[String(r.team)] || {}; return isNum(R.se) ? r.rating - R.se : null; }), hi: top.map(function (r) { var R = ratings[String(r.team)] || {}; return isNum(R.se) ? r.rating + R.se : null; }) }],
      colors: top.map(function (r) { return CC.tcol(L, r.team); }), hrefs: top.map(function (r) { return CC.teamHref(L, r.team, S); }), labelWidth: 96, valName: fb ? 'Rating (points v average)' : 'Margin per 100 possessions', catName: 'Team' });
    if (d.apPts && d.apPts.length) QKC.scatter('#ov-ap', { points: d.apPts.map(function (r) { return { x: r.rank, y: d.mrank[String(r.team)], name: CC.tname(L, r.team), label: CC.tabbr(L, r.team), color: CC.tcol(L, r.team), href: CC.teamHref(L, r.team, S) }; }),
      xName: 'AP rank', yName: 'Our rank', xInverse: false, yInverse: true, diagonal: { label: 'agree' }, labelTop: 10, xMin: 0, yMin: 1 });
    postSnapshot(L, S, post, sim, QK.$('#ov-post', el));
    leaders(L, S, season, QK.$('#ov-leaders', el), QK.$('#ov-hot', el));
  });
});

/* Leaders (after the page has drawn): names come from value.json's leaderboard. */
var LEAD = {
  cfb: [['value', 'Value (EPA above replacement)', 1], ['pass_yds', 'Passing yards', 0], ['rush_yds', 'Rushing yards', 0], ['rec_yds', 'Receiving yards', 0], ['sacks', 'Sacks', 1], ['tkl', 'Tackles', 0]],
  bb: [['value', 'Value above replacement', 1], ['pts', 'Points per game', 1], ['reb', 'Rebounds per game', 1], ['ast', 'Assists per game', 1]]
};
var HOT_EXPL = { value: 'Our value model: what the player adds over a replacement-level player at the same position.', pass_yds: 'Passing yards this season.', rush_yds: 'Rushing yards this season.',
  rec_yds: 'Receiving yards this season.', sacks: 'Sacks this season.', tkl: 'Tackles this season: involvement, not quality.', pts: 'Points a game.', reb: 'Rebounds a game.', ast: 'Assists a game.' };
function leaders(L, S, season, node, hotNode) {
  var LD = season.leaders || {};
  var boards = (CC.fb(L) ? LEAD.cfb : LEAD.bb).filter(function (b) { return (LD[b[0]] || []).length; });
  if (!node || !boards.length) return;
  CC.load(CC.path(L, S, 'value.json')).then(function (v) {
    if (!U.alive(node)) return;
    var names = {};
    ((CC.ok(v) && v.leaders) || []).forEach(function (r) { if (r && r.id && r.name) names[String(r.id)] = r.name; });
    var html = boards.map(function (b) {
      var rows = (LD[b[0]] || []).filter(function (x) { return names[String(x[0])]; }).slice(0, 5);
      if (!rows.length) return '';
      return '<div class="qk-span-' + (boards.length > 4 ? 4 : 3) + '">' + U.card(b[1], '', '<ul class="cc-list cc-lead">' + rows.map(function (x, i) {
        return '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(L, x[0], names[String(x[0])], x[1], null, S) + '<span class="v">' + esc(CC.f(x[2], b[2])) + '</span></li>'; }).join('') + '</ul>', { flush: true }) + '</div>';
    }).join('');
    if (html) node.innerHTML = U.section('The top five', 'This season’s leaders; open Players for percentiles against each position.', '<div class="qk-grid cc-grid">' + html + '</div>', '<a class="qk-more" href="' + esc(CC.href(L, 'players', null, S)) + '">Players</a>', 'Leaderboards');
    var hot = boards.slice(0, 5).map(function (b) {
      var rows = (LD[b[0]] || []).filter(function (x) { return names[String(x[0])]; });
      var r0 = rows[0], r1 = rows[1];
      if (!r0) return null;
      var lab = /^[A-Z][a-z]/.test(b[1]) ? b[1].charAt(0).toLowerCase() + b[1].slice(1) : b[1];
      var fv = function (v) { return b[2] ? CC.f(v, b[2]) : QK.fmt.num(v); };
      return { sport: 'college', title: b[0] === 'value' ? 'Most valuable' : 'Most ' + lab.replace(/ per game$/, ''), name: names[String(r0[0])], value: fv(r0[2]), unit: lab + ' · ' + CC.tabbr(L, r0[1]),
        href: CC.playerHref(L, r0[0], S), next: r1 ? { name: names[String(r1[0])], value: fv(r1[2]) } : null, expl: HOT_EXPL[b[0]] || '' };
    }).filter(Boolean);
    if (hotNode && hot.length) hotNode.innerHTML = U.section('The leaders right now', 'The top of ' + (hot.length === 1 ? 'one' : ['', 'one', 'two', 'three', 'four', 'five'][hot.length]) + ' of our leaderboards, with what each number means.', QK.hotRow(hot), '<a class="qk-more" href="' + esc(CC.href(L, 'players', null, S)) + '">Every player</a>', 'Who’s hot');
  });
}

/* How sure are we? (teaser): the game model's walk-forward record, the full chart on the Model page. Shown only when
   the level's calibration.json is there (CC.calib reads the kit's shape and the builder's own). */
function howSureTeaser(L, box) {
  if (!box) return;
  CC.load(CC.lpath(L, 'calibration.json')).then(function (cj) {
    if (!U.alive(box)) return;
    var cb = CC.calib(cj);
    if (!cb || !cb.bins.length) { box.innerHTML = ''; return; }
    var big = cb.bins.slice().sort(function (x, y) { return y.n - x.n; })[0];
    box.innerHTML = '<article class="qk-card" style="height:100%"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">When we say ' + Math.round(big.mean_p * 100) + '%, it happens ' + Math.round(big.freq * 100) + '% of the time</h3>' +
      '<p style="margin:0 0 6px;color:var(--ink-2)">Our most common call puts the home team at ' + Math.round(big.lo * 100) + '–' + Math.round(big.hi * 100) + '%. Across ' + QK.fmt.num(big.n) + ' games like that, the home team won ' + QK.fmt.pct(big.freq, 1) + '.</p>' +
      QK.note('<b>Brier score ' + (isNum(cb.brier) ? cb.brier.toFixed(3) : '—') + '</b> over ' + QK.fmt.num(cb.n) + ' games, every forecast made before the game with only earlier games: 0 is perfect, 0.25 is a coin flip.') +
      '<a class="qk-more" style="display:inline-block;margin-top:14px" href="' + esc(CC.href(L, 'model', null, null, 'tab=calibration')) + '">The full record</a></div></article>';
  });
}

/* The CFP picture (cfb) or the bracket picture (basketball). */
function postSnapshot(L, S, post, sim, node) {
  if (!node) return;
  var fb = CC.fb(L);
  if (fb) {
    var odds = (post && post.odds) || {};
    /* v3: our chances in teal (no team colours on the bars) */
    var rows = Object.keys(odds).filter(function (t) { return isNum(odds[t].p_in); }).sort(function (a, b) { return odds[b].p_in - odds[a].p_in; }).slice(0, 12);
    if (!rows.length) rows = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_cfp); }).sort(function (a, b) { return sim[b].p_cfp - sim[a].p_cfp; }).slice(0, 12).map(function (t) { odds[t] = { p_in: sim[t].p_cfp, p_bye: sim[t].p_bye, p_title: sim[t].p_title }; return t; });
    if (!rows.length || !(odds[rows[0]].p_in > 0)) { node.innerHTML = U.card('Playoff picture', '', QK.empty('No playoff chances yet', 'They appear once the season simulation has run.')); return; }
    node.innerHTML = U.card('Playoff picture', 'Our chance to make the 12-team College Football Playoff; the sub-line has the bye and the title.', QK.chances(rows.map(function (t) {
      return { label: CC.tshort(L, t), p: odds[t].p_in, sub: (isNum(odds[t].p_bye) ? 'bye ' + CC.pct(odds[t].p_bye) : '') + (isNum(odds[t].p_title) ? ' · title ' + CC.pct(odds[t].p_title) : ''), color: (CC.team(L, t) || {}).colour, href: CC.teamHref(L, t, S), mark: U.mark(L, t) }; }), { max: 1, oursName: 'Our playoff chance' }),
      { foot: '<span>Top 12</span>' + U.link(CC.href(L, 'standings', null, S, 'tab=playoff'), 'Projected bracket and committee proxy') });
    return;
  }
  var bo = (post && post.bracketology) || [];
  var od = (post && post.odds) || {};
  if (post && post.actual && post.actual.regions) {
    var champ = Object.keys(od).filter(function (t) { return isNum((od[t].p_round || {}).Champion); }).sort(function (a, b) { return od[b].p_round.Champion - od[a].p_round.Champion; }).slice(0, 10);
    node.innerHTML = U.card('Our chances when the field was set', 'Pre-tournament title chance, with the seed and the Final Four chance in the sub-line.', QK.chances(champ.map(function (t) {
      return { label: CC.tshort(L, t), p: od[t].p_round.Champion, sub: '(' + (od[t].seed || '—') + ') · Final Four ' + CC.pct(od[t].p_round.F4), color: (CC.team(L, t) || {}).colour, href: CC.teamHref(L, t, S), mark: U.mark(L, t) }; }), { oursName: 'Our title chance' }),
      { foot: '<span>Top 10</span>' + U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'The full bracket') });
    return;
  }
  if (!bo.length) { node.innerHTML = U.card('Bracketology', '', QK.empty('No projected field yet', 'Bracketology appears once the season simulation has run.')); return; }
  node.innerHTML = U.card('Bracketology', 'Projected seed lines from simulated seasons and a selection model fitted on past fields.', '<div id="ov-bo"></div>', { flush: true, foot: '<span>Top 16 by projected seed</span>' + U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'Projected bracket') });
  QK.leaderboard(QK.$('#ov-bo', node), { dense: true, maxHeight: 460, rowHref: function (r) { return CC.teamHref(L, r.team, S); }, columns: [
    { key: 'name', label: 'Team', type: 'entity', mark: function (r) { return U.mark(L, r.team); }, sub: 'record' },
    { key: 'seed_mean', label: 'Seed', num: true, fmt: function (v) { return CC.f(v, 1); }, tip: 'Average projected seed across the simulated seasons' },
    { key: 'p_ncaa', label: 'In field', type: 'bar', max: 1, fmt: function (v) { return CC.pct(v); } },
    { key: 'p_auto', label: 'Auto bid', num: true, fmt: function (v) { return CC.pct(v); }, tip: 'Chance of the conference’s automatic bid' }
  ], rows: bo.slice(0, 16).map(function (r) { return Object.assign({ name: CC.tshort(L, r.team) }, r); }) });
}

})(window.CC);
