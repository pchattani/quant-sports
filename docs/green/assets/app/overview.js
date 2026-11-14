/* The Quant Green — the overview: the featured event, your players, this week with our chances, the week's digest,
 * the power board (our rating split into the parts the striking stats explain), who's hot, the leaders across the
 * tours, stories and who's for real. Reads index.json, overview.json, model.json and scout/men.json (pages.py, depth.py). */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;
var NW = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

function weekCard(w) {
  var live = w.key === 'lwin';
  var rows = (w.top || []).map(function (p) {
    return { label: p.name, p: live ? p.lwin : p.win, href: GR.playerHref(p.pid),
             sub: live ? (GR.toPar(p.tp) || 'not started') : (isNum(p.rt) ? GR.rating(p.rt) + ' a round' : '') };
  });
  var sub = '<b>' + esc(GR.tourName(w.tour)) + '</b> · ' + esc(GR.dates(w.start, w.end)) + (w.course ? ' · ' + esc(w.course) : '') +
    ' · ' + w.field + ' players' + (w.purse ? ' · ' + GR.money(w.purse, true) : '');
  var why = '';
  if (live && w.leader && isNum(w.leader.lwin)) why = w.leader.name + ' leads at ' + (GR.toPar(w.leader.tp) || 'level') + ', our live chance ' + GR.pct(w.leader.lwin) + '.' + (w.fav ? ' Before the start our favourite was ' + w.fav.name + ' at ' + GR.pct(w.fav.win) + '.' : '');
  else if (w.fav && isNum(w.fav.win)) why = 'Our favourite, ' + w.fav.name + ', has ' + GR.pct(w.fav.win) + ' in a field of ' + w.field + ': a chance that comes off ' + GR.oneIn(w.fav.win) + '.';
  var body = QK.chances(rows, { limit: 6, oursName: live ? 'Our live chance to win' : 'Our chance to win', key: true }) + (why ? QK.aside(why, { cls: 'gr-why' }) : '') +
    '<p class="gr-meta"><a href="#/event/' + encodeURIComponent(w.id) + '">' + (live ? 'Live leaderboard and chances' : 'Every player’s chances') + ' →</a>' +
    (w.course_id ? ' · <a href="#/event/' + encodeURIComponent(w.id) + '/course">Course fit →</a>' : '') + '</p>';
  return GR.card(w.name, sub, body, { html: true, cls: 'accent-top', right: GR.statusTag(w.status) });
}

function featured(f) {
  if (!f) return '';
  var live = f.key === 'lwin';
  var rows = (f.top || []).slice(0, 5).map(function (p) { return { label: p.name, p: live ? p.lwin : p.win, href: GR.playerHref(p.pid), sub: live ? GR.toPar(p.tp) : '' }; });
  return '<div class="gr-feat qk-card"><div class="qk-card-body"><div class="qk-sh-kicker">' + esc((live ? 'Live now' : 'The one to watch') + (f.major ? ' · a major' : '')) + '</div>' +
    '<h2 class="gr-feat-t"><a href="#/event/' + encodeURIComponent(f.id) + '">' + esc(f.name) + '</a></h2><p class="gr-meta">' + esc(GR.tourName(f.tour) + ' · ' + GR.dates(f.start, f.end) + (f.course ? ' · ' + f.course : '')) + '</p>' +
    QK.chances(rows, { limit: 5, oursName: live ? 'Live chance to win' : 'Our chance to win', key: false }) + '</div></div>';
}

function digestTiles(d, idx) {
  if (!d || !(d.events || []).length) return '';
  var t = [];
  var n = d.events.length;
  t.push({ label: 'Events', value: String(n), sub: GR.date(d.from) + (d.to && d.to !== d.from ? ' to ' + GR.date(d.to) : '') });
  /* our record (favourites won) lives on the Model page, not here (STYLE_GUIDE §3, round 6) */
  if (d.longshot && d.longshot.winner) t.push({ label: 'Biggest upset', value: d.longshot.winner.name, text: true, href: '#/event/' + encodeURIComponent(d.longshot.id),
    sub: 'We gave them ' + GR.pct(d.longshot.winner.win) + ' to win the ' + d.longshot.name + '.' });
  if (d.low) t.push({ label: 'Round of the week', value: d.low.name, text: true, href: GR.playerHref(d.low.pid),
    sub: d.low.strokes + ' in round ' + d.low.round + ' of the ' + d.low.ev + ': ' + GR.signed(d.low.sg, 1) + ' strokes on an average field (' + fmt.num(d.low.field, 1) + ').' });
  return QK.stats(t);
}

function results(d) {
  var ev = (d && d.events) || [];
  if (!ev.length) return '';
  return '<ul class="gr-list gr-cols2">' + ev.map(function (e) {
    var w = e.winner || {};
    return '<li><span>' + GR.eventLink(e.id, e.name) + (e.major ? ' ' + QK.tag('Major') : '') + ' <span class="gr-muted">' + esc(GR.tourShort(e.tour)) + '</span></span><span class="num">' + GR.toParHTML(w.tp) + '</span>' +
      '<small>Won by ' + (w.pid ? GR.playerLink(w.pid, w.name) : esc(w.name || '')) + (isNum(w.win) ? ', our pre-event chance ' + GR.pct(w.win) : '') +
      (e.fav && e.fav.pid !== w.pid ? '; our favourite was ' + esc(e.fav.name) + ' (' + GR.pct(e.fav.win) + ')' : e.fav ? ' (our favourite)' : '') + '</small></li>';
  }).join('') + '</ul>';
}

var PARTS = [{ key: 'ott', label: 'Off the tee (est.)', color: 'var(--c-1)' }, { key: 'app', label: 'Approach (est.)', color: 'var(--c-3)' },
  { key: 'sg', label: 'Short game and putting (est.)', color: 'var(--c-4)' }, { key: 'other', label: 'Not explained by the stats', color: 'var(--c-other)' }];
function powerBoard(rows, stream) {
  if (!QK.powerBars || !rows || !rows.length) return '';
  return QK.powerBars(null, { groups: [{ label: '', rows: rows.map(function (r) {
    var m = GR.mark(r.name, r.tour);
    var last = (r.l5 || []).slice(-5).map(function (x) { return x[3] === 'finish' ? (x[2] ? 'T' : '') + x[1] : x[3] === 'cut' ? 'MC' : String(x[3] || '').toUpperCase(); }).join(' ');
    return { rank: r.rank, name: r.name, abbr: m.abbr, colour: m.colour, href: GR.playerHref(r.pid), value: r.rt, text: GR.rating(r.rt),
      parts: r.parts || {}, follow: GR.followItem(r.pid, r.name, stream),
      cells: [{ label: '12 months', text: (r.wins || 0) + ' wins, ' + (r.top10 || 0) + ' top 10s' }, { label: 'Last five', text: last || 'none' }],
      sub: GR.tourShort(r.tour) + (isNum(r.d90) && Math.abs(r.d90) >= 0.05 ? ' · ' + GR.signed(r.d90, 2) + ' in 90 days' : '') };
  }) }], parts: stream === 'men' ? PARTS : [], valueLabel: 'Our rating', unit: 'strokes a round v an average tour player' });
}

function stories(list) {
  var items = (list || []).map(function (s) {
    var who = (s.stream === 'women' ? 'LPGA' : 'Men') + ' · ';
    if (s.kind === 'riser' || s.kind === 'faller') {
      return { sport: 'golf', kicker: who + (s.kind === 'riser' ? 'Biggest riser' : 'Biggest faller'), name: s.name, sub: 'Our rating, 90 days', value: GR.signed(s.d, 2), unit: 'strokes a round',
        href: GR.playerHref(s.pid), spark: s.spark, sparkLabel: 'Rating before each event, the last 12 months',
        text: s.name + (s.kind === 'riser' ? ' is ' + fmt.num(Math.abs(s.d), 2) + ' strokes a round better than 90 days ago in our numbers, now ' + GR.rating(s.rt) + '.' : ' has dropped ' + fmt.num(Math.abs(s.d), 2) + ' strokes a round in 90 days, now ' + GR.rating(s.rt) + '.') };
    }
    if (s.kind === 'hot') return { sport: 'golf', kicker: who + 'Running hot', name: s.name, sub: 'Last eight events against the rating', value: GR.signed(s.form - s.rt, 2), unit: 'strokes a round',
      href: GR.playerHref(s.pid), text: s.name + ' has averaged ' + GR.signed(s.form, 2) + ' strokes gained a round over the last eight events, ' + fmt.num(s.form - s.rt, 2) + ' better than a rating of ' + GR.rating(s.rt) + ': the best run against expectation among the regulars.' };
    if (s.kind === 'cuts') return { sport: 'golf', kicker: who + 'Cut machine', name: s.name, sub: 'Cuts made in a row', value: String(s.n), unit: 'events', href: GR.playerHref(s.pid),
      text: s.name + ' has made the last ' + s.n + ' cuts in a row, the longest current run among the ranked players.' };
    return null;
  }).filter(Boolean);
  return items.length ? QK.storyCards(items, { cols: 3 }) : '';
}

function stars(list) {
  var men = (list || []).filter(function (x) { return x.stream === 'men'; });
  if (!men.length || !QK.hotRow) return '';
  return QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The best on each number', sub: 'The leader on key numbers among the regulars of the last two years (30 rounds or more), every men’s tour on one scale. Strokes gained are against an average field; rates are shrunk toward the tour average so a short record cannot top a list.',
    actions: '<a class="qk-more" href="#/scout?view=leaders">Every leader</a>' }) +
    QK.hotRow(men.map(function (x) {
      return { sport: 'golf', kicker: x.label, name: x.name, value: GR.vfmt(x.m, x.v), title: GR.tourName(x.tour), next: x.next ? { name: x.next.name, value: GR.vfmt(x.m, x.next.v) } : null, href: GR.playerHref(x.pid) };
    })));
}

var LD = { all: ['sg', 'form', 'h4', 'h5', 'bird', 'bog', 'great', 't10'], pga: ['sg', 'dist', 'acc', 'gir', 'ppg', 'sand', 'h3', 'h5'] };
function leaders(el) {
  if (!el || !window.QKL || !QKL.leaders || !QKL.board) return;
  GR.maybe('scout/men.json').then(function (bd) {
    if (!bd || !el.isConnected) return;
    var cols = bd.cols || [], rows = (bd.rows || []).map(function (r) { var o = {}; for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i]; return o; }).filter(function (r) { return r.q; });
    var M = {};
    (bd.metrics || []).forEach(function (m) { M[m.id] = m; });
    var mk = function (ids, rs) {
      return ids.filter(function (id) { return M[id]; }).map(function (id) {
        var m = M[id];
        return QKL.board(rs.filter(function (r) { return isNum(r[id]); }).map(function (r) { return { id: r.id, name: r.n, team: r.tour, v: r[id] }; }),
          { key: id, label: m.label, unit: '', dir: m.dir, fmt: GR.lfmt(id), ours: id === 'sg' || id === 'form' ? 'Strokes gained' : '', tip: m.tip }, 5);
      }).filter(function (x) { return x.n > 1; });
    };
    var views = [{ key: 'all', label: 'Every men’s tour', entity: 'player', peer: 'regulars', min: '30 rounds in two years', metrics: mk(LD.all, rows) }];
    ['pga', 'eur', 'liv', 'ntw'].forEach(function (t) {
      var rs = rows.filter(function (r) { return r.tour === t; });
      if (rs.length >= 12) views.push({ key: t, label: GR.tourName(t), entity: 'player', peer: GR.tourShort(t) + ' regulars', min: '30 rounds in two years', metrics: mk(t === 'pga' ? LD.pga : LD.all, rs) });
    });
    QKL.leaders(el, { data: { views: views }, title: 'Who leads, and who is struggling',
      sub: 'The top and the bottom of the regulars on each key number, across the men’s tours and tour by tour. The striking numbers are PGA Tour season statistics (ESPN); everything else is from the scores.',
      team: function (k) { var m = GR.mark(GR.tourShort(k), k); return { abbr: GR.tourShort(k), name: GR.tourName(k), colour: m.colour }; },
      href: function (id) { return GR.playerHref(id); }, scope: 'tour' });
  });
}

/* My Players: each followed golfer with rank, rating, the last finish and this week's chance where entered */
function followBoard(rk, idx) {
  var mine = GR.followed();
  if (!mine.length) return '';
  var by = {};
  ['men', 'women'].forEach(function (s) { ((rk && rk[s]) || []).forEach(function (r) { by[r.pid] = r; }); });
  var week = {};
  (idx.week || []).forEach(function (w) { (w.top || []).forEach(function (p) { week[p.pid] = { ev: w.name, id: w.id, p: w.key === 'lwin' ? p.lwin : p.win }; }); });
  var rows = mine.map(function (m) {
    var r = by[m.pid] || {};
    var l = (r.l5 || []).slice(-1)[0];
    var wk = week[m.pid];
    return [{ v: m.name, html: GR.followStar(m.pid, m.name, m.stream) + GR.playerLink(m.pid, r.name || m.name) }, { v: r.rank || 999, html: r.rank ? String(r.rank) : '<span class="gr-muted">unranked</span>' },
      { v: r.rt || -9, html: GR.rating(r.rt) }, { v: r.d90 || 0, html: GR.signed(r.d90, 2) },
      { v: l ? l[1] || 999 : 999, html: l ? (l[3] === 'finish' ? (l[2] ? 'T' : '') + l[1] : 'MC') + ' ' + GR.eventLink(l[0], 'event') : '' },
      { v: wk ? wk.p : -1, html: wk ? GR.pct(wk.p) + ' in ' + GR.eventLink(wk.id, wk.ev) : '<span class="gr-muted">not among this week’s favourites</span>' }];
  });
  return '<div class="qk-card"><div class="qk-card-body flush">' + GR.table([{ label: 'Player', align: 'left' }, { label: 'Rank' }, { label: 'Rating' }, { label: '90 days' }, { label: 'Last' }, { label: 'This week', align: 'left' }], rows) + '</div></div>';
}

GR.page('overview', function (el) {
  return Promise.all([GR.load('index.json'), GR.maybe('overview.json'), GR.maybe('rankings.json')]).then(function (r) {
    if (!el.isConnected) return;
    var ix = r[0], ov = r[1] || {}, rk = r[2];
    var html = QK.greeting({ date: 'Golf · PGA Tour, DP World Tour, LIV, Korn Ferry and LPGA',
      title: 'Golf, ' + QK.mark('by the numbers') + '.', lede: 'Every round since 2001 measured against the field that played it: ratings in strokes a round, chances for every event from 20,000 simulated tournaments, the Scouting Room, courses and a Lab. Updated ' + fmt.ago(ix.updated_at) + '.',
      ctas: [{ label: 'This week’s chances', href: '#/fixtures' }, { label: 'Scouting Room', href: '#/scout', ghost: true }, { label: 'Rankings', href: '#/standings', ghost: true }],
      side: featured(ov.featured) });
    html += '<section class="qk-section gr-follow" id="gr-follow"></section>';
    var week = (ix.week || []).length ? '<div class="gr-week">' + ix.week.map(weekCard).join('') + '</div>' : QK.empty('No event this week', 'The next events appear here once their fields are set.');
    html += GR.sec('This week', (ix.week || []).length === 1 ? 'One event. Our call.' : (ix.week || []).length + ' events. Our calls.', 'Live events show chances from the scores so far; upcoming ones, our pre-event chances for the field as entered.', week, '<a class="qk-more" href="#/fixtures">Every event</a>');
    var dg = ov.digest;
    if (dg && (dg.events || []).length) html += GR.sec('The week in golf', 'The last ' + (NW[dg.events.length] || dg.events.length) + (dg.events.length === 1 ? ' event' : ' events'), 'Winners, what we gave them before the event, the biggest upset and the round of the week against the field.', digestTiles(dg, ix) + results(dg));
    var pw = ov.power || {};
    html += GR.sec('Power board', 'Who is best right now?', 'Our rating is strokes a round better than an average PGA Tour player. For the men, the bar splits it into what the PGA Tour’s season statistics explain (our estimate: off the tee, approach, short game and putting) and the rest. Players without PGA Tour statistics show the rating alone. Star a player to follow them.',
      powerBoard(pw.men, 'men'), '<a class="qk-more" href="#/power">Power rankings</a> <a class="qk-more" href="#/standings">Every ranked player</a>');
    html += '<div id="ov-stars"></div><section class="qk-section" id="ov-leaders"></section>';
    html += GR.sec('LPGA', 'The top of the women’s game', 'Strokes a round better than an average LPGA Tour player.', powerBoard(pw.women, 'women'), '<a class="qk-more" href="#/standings?s=women">Every ranked player</a>');
    html += GR.sec('Stories', 'What the numbers say', 'Movers, runs and the players doing more than their rating says.', stories(ov.stories) +
      '<div class="qk-g75 gr-real"><div>' + GR.card('Who’s for real?', 'Our rating across, the share of starts finishing in the top 10 over 12 months up. Above the cloud: finishing better than the rating suggests (a hot putter, weak fields); below: the reverse.', GR.chart('ov-quad', 380, 'Rating against top-10 rate')) +
      '</div><div>' + QK.newHere({ items: ['A <b>chance</b> is how often we think something happens. A 20% favourite still loses four times in five.',
        'A <b>rating</b> is strokes a round better than an average tour player: +2 beats an average field by eight shots over four rounds.',
        'A <b>percentile</b> ranks a player against the regulars of the last two years. <a class="qk-link" href="#/model">How it all works</a>.'] }) + '</div></div>');
    /* our record lives on the Model page (STYLE_GUIDE §3, round 6): a small link from the foot, no record tiles here */
    html += '<p class="gr-meta gr-foot-link"><a href="#/model?tab=doing">How our forecasts have done on seasons the model never saw →</a></p>';
    el.innerHTML = html;
    var fl = el.querySelector('#gr-follow');
    if (fl && QK.followSection) QK.followSection(fl, { site: 'green', full: true, feed: false, title: 'Your players', noun: 'player',
      sub: 'The players you follow, first: this week’s event with our chances, our rating and rank, form (W a top 10, D another made cut, L a missed cut) and the facts that stand out.',
      picker: { sport: 'golf', rows: ((rk && rk.men) || []).slice(0, 150).concat(((rk && rk.women) || []).slice(0, 60)).map(function (x, i) {
        var s = i < Math.min(150, ((rk && rk.men) || []).length) ? 'men' : 'women';
        var it = GR.followItem(x.pid, x.name, s);
        return { sport: 'golf', t: x.name, s: (s === 'men' ? 'Men' : 'LPGA') + ' · ranked ' + x.rank, k: it.k, href: it.href, abbr: it.abbr, go: i };
      }) }, board: function () { return followBoard(rk, ix); } });
    var st = el.querySelector('#ov-stars');
    if (st) st.innerHTML = stars(ov.stars);
    leaders(el.querySelector('#ov-leaders'));
    var real = (ov.real || {}).men || [];
    GR.safe(function () {
      if (real.length >= 5 && QKC.quadrant) QKC.quadrant(el.querySelector('#ov-quad'), { points: real.map(function (p) {
        return { x: p.x, y: p.y * 100, label: GR.surname(p.name), name: p.name, href: GR.playerHref(p.pid), sub: p.n + ' starts in 12 months' }; }),
        xName: 'Our rating (strokes a round v an average PGA Tour player)', yName: 'Top-10 finishes in 12 months (%)', yFmt: function (v) { return Math.round(v) + '%'; } });
    });
  });
});
})();
