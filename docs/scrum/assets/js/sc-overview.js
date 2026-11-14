/* The Quant Scrum — the overview (landing page) of a scope: the intro band with the featured test, My Teams, "This week
 * in rugby" top lines, the upcoming tests with our chances, the power board, who's hot by position, the title races,
 * stories and who's for real. Reads <S>/overview.json (oddsmarkets/rugby/pages.py overview_payload). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;

function featHero(S, f) {
  if (!f) return '';
  var g = SC.game(S, f);
  var tag = f.status === 'final' ? 'The last big test' : (SC.compName(f.comp) + ' · the one to watch');
  var note = f.status !== 'final' && isNum(f.m) ? '<b>How sure are we?</b> We expect ' + esc(SC.tname(S, f.m >= 0 ? f.home : f.away)) + ' to win by about ' +
    Math.max(1, Math.round(Math.abs(f.m))) + (isNum(f.t) ? ', in a test of about ' + Math.round(f.t) + ' points' : '') + '. Half of tests land within about eight points of our margin.' : undefined;
  return QK.featureCard(g, { scribble: tag, note: note });
}

function digestTiles(S, d) {
  if (!d || !d.n) return '';
  var t = [];
  t.push({ label: 'Tests', value: String(d.n), sub: SC.date(d.from) + (d.to !== d.from ? ' to ' + SC.date(d.to) : '') });
  if (d.record && d.record.n) t.push({ label: 'Our favourites', value: d.record.won + ' of ' + d.record.n, signal: true, sub: 'We expected about ' + Math.round(d.record.expected) + '.' });
  if (d.upset) t.push({ label: 'The upset', value: SC.tabbr(S, d.upset.winner) + ' ' + d.upset.score[0] + '–' + d.upset.score[1], href: SC.matchHref(S, d.upset.id),
    sub: 'We gave ' + SC.tname(S, d.upset.winner) + ' ' + SC.pct(d.upset.p) + ' against ' + SC.tname(S, d.upset.loser) + '.' });
  if (d.biggest) t.push({ label: 'Biggest win', value: SC.tabbr(S, d.biggest.winner) + ' ' + d.biggest.score[0] + '–' + d.biggest.score[1], href: SC.matchHref(S, d.biggest.id),
    sub: SC.tname(S, d.biggest.winner) + ' over ' + SC.tname(S, d.biggest.loser) + '.' });
  if (d.tries) t.push({ label: 'Most tries', value: String(d.tries.k), href: SC.playerHref(S, d.tries.id), sub: d.tries.n + '.' });
  return QK.stats(t);
}

function upcomingGrid(S, list) {
  if (!list || !list.length) return QK.empty('No tests scheduled in the next three weeks', 'The next fixtures appear here as soon as they are announced.');
  return '<div class="qk-watch sc-watch">' + list.slice(0, 9).map(function (c) {
    var g = SC.game(S, c);
    var why = isNum(c.m) ? SC.margin(S, c) + (isNum(c.p && c.p[1]) && c.p[1] >= 0.03 ? ' · draw ' + SC.pct(c.p[1]) : '') + (isNum(c.t) ? ' · about ' + Math.round(c.t) + ' points' : '') : '';
    return QK.gameCard(g, { sport: false, homeFirst: true, why: why || false, market: false, form: false });
  }).join('') + '</div>';
}

function powerBoard(S, rows) {
  if (!QK.powerBars || !rows || !rows.length) return '';
  var pp = SC.powerParts(rows), parts = pp.parts;
  return QK.powerBars(null, { groups: [{ label: '', rows: rows.slice(0, 16).map(function (r) {
    var t = SC.team(S, r.id) || {};
    return { rank: r.rank, name: t.name, abbr: t.abbr, colour: t.colour, href: SC.teamHref(S, r.id), value: r.rating, text: SC.signed(r.rating, 1),
      parts: pp.of(r), form: r.form, follow: SC.followItem(S, r.id),
      cells: [{ label: 'World Rugby rank', text: r.wr_rank ? QK.ordinal(r.wr_rank) : '—' }, { label: 'Last 12 months', text: (r.rec12 || []).join('–') }],
      sub: isNum(r.d30) && Math.abs(r.d30) >= 0.05 ? SC.signed(r.d30, 1) + ' in 30 days' : '' };
  }) }], parts: parts, valueLabel: 'Our rating', unit: 'points v an average test side', formN: 5, formLabel: 'Last 5' });
}

function stories(S, list) {
  var items = (list || []).map(function (s) {
    var t = SC.team(S, s.team) || {};
    if (s.kind === 'riser' || s.kind === 'faller') {
      return { sport: 'rugby', kicker: s.kind === 'riser' ? 'Biggest riser' : 'Biggest faller', name: t.name, sub: 'Our rating, the last 12 months',
        value: SC.signed(s.d, 1), unit: 'points', mark: SC.mark(S, s.team), colour: t.colour, href: SC.teamHref(S, s.team),
        spark: (s.hist || []).map(function (h) { return h[1]; }), sparkLabel: 'Rating, month by month',
        text: t.name + (s.kind === 'riser' ? ' are ' + SC.f(Math.abs(s.d), 1) + ' points better than a year ago in our numbers, now ' + SC.signed(s.rating, 1) + '.' : ' have dropped ' + SC.f(Math.abs(s.d), 1) + ' points in a year, now ' + SC.signed(s.rating, 1) + '.') };
    }
    if (s.kind === 'run') {
      return { sport: 'rugby', kicker: 'On a run', name: t.name, sub: 'Consecutive test wins', value: s.n, unit: 'wins', mark: SC.mark(S, s.team), colour: t.colour,
        href: SC.teamHref(S, s.team), text: t.name + ' have won their last ' + s.n + ' tests.' };
    }
    return null;
  }).filter(Boolean);
  return items.length ? QK.storyCards(items, { cols: 3 }) : '';
}

function races(S, rs) {
  if (!rs || !rs.length) return '';
  return '<div class="sc-races">' + rs.map(function (r) {
    var rows = r.rows.filter(function (x) { return isNum(x.p) && x.p > 0.0005; }).map(function (x) {
      var id = SC.byName(S, x.team);
      return { label: x.team, p: x.p, href: id ? SC.teamHref(S, id) : null, color: id ? SC.traw(S, id) : null, mark: id ? SC.mark(S, id) : null };
    });
    var dec = QK.decided ? QK.decided(rows) : null;
    var title = { nc: 'Who wins the Nations Championship?', six: 'Who wins the ' + r.season + ' Six Nations?', rwc: 'Who lifts the ' + r.season + ' World Cup?', trc: 'Who wins the Rugby Championship?' }[r.comp] || SC.compName(r.comp);
    return '<div class="sc-race">' + QK.sectionHead({ kicker: 'Title race', title: esc(title), html: true, actions: '<a class="qk-more" href="' + esc(SC.href(S, 'standings', null, 'tab=' + r.comp)) + '">Standings</a>' }) +
      (dec ? QK.explain('<b>' + esc(dec.label) + '</b> have won it.') : QK.chances(rows, { key: false, limit: 6, oursName: 'Our title chance' })) + '</div>';
  }).join('') + '</div>';
}

function stars(S, list) {
  if (!list || !list.length) return '';
  return QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The best in each position, on value', sub: 'Our Scrum value per 80 minutes over the last two years, the leader in each position group among regular test players. ' +
    'Points added above a replacement-level player in the same position.', actions: '<a class="qk-more" href="' + esc(SC.href(S, 'scout', null, 'view=leaders')) + '">Every position</a>' }) +
    QK.hotRow(list.map(function (x) {
      return { sport: 'rugby', kicker: SC.GROUP[x.grp] + ' · ' + SC.tabbr(S, x.team), name: x.n, value: SC.signed(x.v, 1), title: 'points per 80 above replacement',
        next: x.next ? { name: x.next.n, value: SC.signed(x.next.v, 1) } : null, href: SC.playerHref(S, x.id) };
    })));
}

/* Top and bottom performers across test rugby (QKL.leaders, as Hardwood's league pages): every key number of each
   position group, the five best and the five at the bottom among the regulars */
var LD_HEAD = { all: ['val80', 'inv', 'm', 'cb', 'tk', 'tkpct', 'pc'], front_row: ['val80', 'tk', 'tkpct', 'car', 'lopct'], lock: ['val80', 'tk', 'tkpct', 'car', 'ml'],
  back_row: ['val80', 'tk', 'car', 'm', 'db'], halves: ['val80', 'pts', 'pas', 'kfh', 'gkp'], centres: ['val80', 'm', 'cb', 'db', 'off'], back_three: ['val80', 'm', 'cb', 'db', 'tries'] };
function leaders(el, S) {
  if (!el || !window.QKL || !QKL.leaders || !QKL.board) return;
  SC.load(S + '/players.json').then(function (bd) {
    if (!SC.ok(bd) || !U.alive(el)) return;
    var cols = bd.cols || [], rows = (bd.rows || []).map(function (r) { var o = {}; for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i]; return o; }).filter(function (r) { return r.q; });
    var M = {};
    (bd.metrics || []).forEach(function (m) { M[m.id] = m; });
    var mk = function (ids, rs) {
      return ids.filter(function (id) { return M[id]; }).map(function (id) {
        var m = M[id];
        return QKL.board(rs.map(function (r) { return { id: r.id, name: r.n, team: r.team, v: r[id] }; }), { key: id, label: m.label, unit: '', dir: m.dir === 'lower' ? 'lower' : 'higher',
          fmt: (id === 'tkpct' || id === 'kpct' || id === 'lopct') ? 'pct1' : id === 'val80' ? '+1' : '1', ours: id === 'val80' ? 'Scrum value' : '', tip: '' }, 5);
      }).filter(function (x) { return x.n > 1; });
    };
    var views = [{ key: 'all', label: 'All players', entity: 'player', peer: 'regulars', min: '160 minutes in the last two years', metrics: mk(LD_HEAD.all, rows) }];
    Object.keys(SC.GROUP).forEach(function (g) {
      var rs = rows.filter(function (r) { return r.grp === g; });
      if (rs.length >= 8) views.push({ key: g, label: SC.GROUP[g], entity: 'player', peer: SC.GROUP[g].toLowerCase(), min: '160 minutes in the last two years', metrics: mk(LD_HEAD[g], rs) });
    });
    QKL.leaders(el, { data: { views: views }, title: 'Who leads test rugby, and who is struggling',
      sub: 'The leaders and the bottom of the regulars on each key number, overall and by position group. Rates per 80 minutes over the last two years, shrunk toward the position average.',
      team: function (k) { var t = SC.team(S, k) || {}; return { abbr: t.abbr, name: t.name, colour: t.colour, href: SC.teamHref(S, k) }; },
      href: function (id) { return SC.playerHref(S, id); }, scope: 'field' });
  });
}

/* "Your teams in our ratings" (Rink's "Your clubs v the league"): each followed side with the sides either side of it */
var RATED = {};
function followBoard(S, cards) {
  var rr = RATED[S];
  if (!QK.powerBars || !rr || rr.length < 3) return '';
  var mine = {};
  cards.forEach(function (c) { var p = String(c.k || '').split(':'); if (p[0] === 'scrum' && p[1] === S) mine[p[2]] = 1; });
  var keep = {};
  rr.forEach(function (r, i) { if (mine[r.id]) [i - 1, i, i + 1].forEach(function (j) { if (j >= 0 && j < rr.length) keep[j] = 1; }); });
  var ix = Object.keys(keep).map(Number).sort(function (a, b) { return a - b; });
  if (!ix.length) return '';
  var groups = [];
  ix.forEach(function (i, n) { if (!n || i !== ix[n - 1] + 1) groups.push({ label: '', rows: [] }); groups[groups.length - 1].rows.push(i); });
  groups.forEach(function (g) {
    g.rows = g.rows.map(function (i) {
      var r = rr[i], t = SC.team(S, r.id) || {};
      return { rank: r.rank, name: t.name, abbr: t.abbr, colour: t.colour, href: SC.teamHref(S, r.id), value: r.rating, text: SC.signed(r.rating, 1), follow: SC.followItem(S, r.id),
        sub: (r.rec12 || []).join('–') + ' in 12 months' + (mine[r.id] ? ' · you follow' : '') };
    });
  });
  return '<div class="sc-flboard"><div class="qk-fc-k">Your teams in our ratings</div><div class="qk-card"><div class="qk-card-body">' +
    QK.powerBars(null, { groups: groups, valueLabel: 'Our rating', unit: 'points v an average test side', key: false }) +
    '<p class="qk-caption">Each side you follow in our ranking of ' + rr.length + ', with the sides either side. Provisional ratings are not ranked. <a class="qk-link" href="' + esc(SC.href(S, 'rankings', null, 'tab=ours')) + '">Every side →</a></p></div></div></div>';
}

function quadrant(el, S, pts) {
  if (!el || !pts || pts.length < 5 || !window.QKC || !QKC.quadrant) return;
  QKC.quadrant(el, { points: pts.map(function (p) {
    var t = SC.team(S, p.id) || {};
    return { x: p.x, y: p.y * 100, label: t.abbr, name: t.name, color: t.colour, href: SC.teamHref(S, p.id), sub: p.n + ' tests in two years' };
  }), xName: 'Our rating (points v an average side)', yName: 'Tests won in the last two years (%)', yFmt: function (v) { return Math.round(v) + '%'; } });
}

SC.route('overview', function (page, P) {
  var S = P.S;
  page.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([SC.load(S + '/overview.json'), SC.load(S + '/ratings.json')]).then(function (res) {
    var d = res[0], rt = res[1];
    if (SC.ok(rt)) RATED[S] = (rt.teams || []).filter(function (t) { return isNum(t.rank); });
    if (!SC.ok(d)) { page.innerHTML = U.head(SC.SNAME[S], '', SC.SITE) + U.missing('The overview', d); return; }
    var info = SC.info(S);
    var next = (d.upcoming || [])[0];
    var lede = (S === 'men' ? 'Every men’s test since 1995 (box scores and player stats since about 2006): ' : 'The women’s tests our source carries: ') +
      'our chance for every match, ratings with home advantage, travel and rest taken out, our rebuild of the World Rugby rankings, title chances from 20,000 simulated tournaments, and every player measured against their position.';
    var html = QK.greeting({ date: SC.SNAME[S] + (next ? ' · next test ' + SC.date(next.date) : ''),
      title: 'International rugby, ' + QK.mark('by the numbers') + '.', lede: lede,
      ctas: [{ label: 'Fixtures and chances', href: SC.href(S, 'fixtures') }, { label: 'Rankings', href: SC.href(S, 'rankings'), ghost: true }, { label: 'Standings', href: SC.href(S, 'standings'), ghost: true }],
      side: featHero(S, d.featured) });
    html += '<section class="qk-section sc-follow" id="sc-follow"></section>';
    var dg = d.digest || {};
    var NW = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
    html += U.sec(dg.label === 'This week' ? 'This week in rugby' : 'The last test weekend', dg.n ? 'The week in ' + (NW[dg.n] || dg.n) + (dg.n === 1 ? ' test' : ' tests') : 'Quiet week', dg.n ? 'Results, how our favourites did, the upset and the biggest win.' : '',
      digestTiles(S, dg) + (dg.results && dg.results.length ? '<div class="sc-results-strip">' + dg.results.slice(-6).map(function (c) { return SC.card(S, c, { why: true }); }).join('') + '</div>' : ''));
    html += U.sec('Upcoming tests', (d.upcoming || []).length ? (d.upcoming.length === 1 ? 'One test. Our call.' : Math.min(9, d.upcoming.length) + ' tests. Our calls.') : 'Nothing scheduled yet',
      'Our chance for each side, the draw where it is live, and the margin and total we expect. Click a test for the full forecast.', upcomingGrid(S, d.upcoming),
      '<a class="qk-more" href="' + esc(SC.href(S, 'fixtures')) + '">Every fixture</a>');
    html += '<div id="ov-races"></div>';
    html += U.sec('Power board', 'Who is best right now?', 'Our rating is points better than an average test side on a neutral ground, split into attack (points scored above average) and defence (points kept out). The rank is ours; the World Rugby rank beside it is our rebuild of the official table, a different system, so the two can disagree. Sides that rarely meet tier-one and tier-two opposition are not ranked: their ratings are provisional.',
      powerBoard(S, d.power), '<a class="qk-more" href="' + esc(SC.href(S, 'power')) + '">Power rankings</a><a class="qk-more" href="' + esc(SC.href(S, 'rankings', null, 'tab=ours')) + '">Every side</a>');
    html += '<div id="ov-stars"></div><div id="ov-leaders"></div>';
    html += U.sec('Stories', 'What the numbers say', 'Movers, runs and the sides doing more (or less) than their rating says.', stories(S, d.stories) +
      '<div class="qk-g75 sc-real"><div>' + U.card('Who’s for real?', 'Our rating across, the share of tests won over two years up. Top-left: winning more than the rating suggests (a soft schedule, close wins). Bottom-right: the reverse.', U.chart('ov-quad', 380, 'Rating against tests won')) +
      '</div><div>' + QK.newHere({ items: ['A <b>chance</b> is how often we think something happens. 70% still loses 3 times in 10.',
        'A <b>rating</b> is points better than an average test side on a neutral ground: +10 beats an average side by ten.',
        'A <b>percentile</b> ranks a player against regular test players in the same position. <a class="qk-link" href="' + esc(SC.href(S, 'model')) + '">How it all works</a>.'] }) + '</div></div>');
    var c = d.counts || {};
    html += '<p class="sc-note">' + esc(fmt.num(c.matches || 0)) + ' tests since ' + esc(c.from || '') + ', ' + esc(fmt.num(c.teams || 0)) + ' sides and ' + esc(fmt.num(c.players || 0)) + ' players in our data. ' +
      'How well our forecasts have done lives on the <a href="' + esc(SC.href(S, 'model', null, 'tab=doing')) + '">Model page</a>.</p>';
    page.innerHTML = html;
    var fl = QK.$('#sc-follow', page);
    if (fl && QK.followSection) QK.followSection(fl, { site: 'scrum', scope: S, full: true, feed: false, title: 'Your teams',
      scopeLabel: function (s) { return SC.SNAME[s] || s; }, scopeHref: function (s) { return '#/' + s; },
      picker: { sport: 'rugby', rows: SC.followRows() }, board: function (cards) { return followBoard(S, cards); } });
    var rn = QK.$('#ov-races', page);
    if (rn && d.races && d.races.length) rn.innerHTML = '<section class="qk-section sc-sec">' + races(S, d.races) + '</section>';
    var st = QK.$('#ov-stars', page);
    if (st) st.innerHTML = stars(S, d.stars);
    quadrant(QK.$('#ov-quad', page), S, d.real);
    leaders(QK.$('#ov-leaders', page), S);
  });
});
})();
