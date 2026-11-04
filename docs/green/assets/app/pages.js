/* The Quant Green — overview, events, rankings, players, player, model and terms pages. The event page is event.js. */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;

function chartSafe(fn) { try { fn(); } catch (e) { if (window.console) console.error(e); } }

// ── overview ───────────────────────────────────────────────────────────────

function weekCard(w) {
  var live = w.key === 'lwin';
  var rows = (w.top || []).map(function (p) {
    return { label: p.name, p: live ? p.lwin : p.win, href: '#/player/' + encodeURIComponent(p.pid),
             sub: live ? GR.toPar(p.tp) : (isNum(p.rt) ? GR.rating(p.rt) + ' a round' : '') };
  });
  var sub = '<b>' + esc(GR.tourName(w.tour)) + '</b> · ' + esc(GR.dates(w.start, w.end)) + (w.course ? ' · ' + esc(w.course) : '') +
    ' · ' + w.field + ' players' + (w.purse ? ' · ' + GR.money(w.purse, true) : '');
  var body = QK.chances(rows, { limit: 8, oursName: live ? 'Our live chance to win' : 'Our chance to win', key: true }) +
    '<p class="gr-meta"><a href="#/event/' + encodeURIComponent(w.id) + '">' + (live ? 'Live leaderboard and chances' : 'Every player\u2019s chances') + ' \u2192</a></p>';
  return GR.card(w.name, sub, body, { html: true, cls: 'accent-top', right: GR.statusTag(w.status) });
}

function topTable(rows, href) {
  return '<ol class="gr-list">' + (rows || []).map(function (r) {
    return '<li><span>' + r.rank + '. ' + GR.playerLink(r.pid, r.name) + ' <span class="gr-muted">' + esc(r.cc || '') + '</span></span><b class="num">' + GR.rating(r.rt) + '</b></li>';
  }).join('') + '</ol><p class="gr-meta"><a href="' + href + '">Full rankings \u2192</a></p>';
}

GR.page('overview', function (el) {
  return Promise.all([GR.load('index.json'), GR.load('model.json').catch(function () { return null; })]).then(function (r) {
    if (!el.isConnected) return;
    var ix = r[0], m = r[1];
    var ev = m && m.events;
    var head = QK.sectionHead({ tag: 'h1', size: 'lg', kicker: 'Golf by the numbers', title: 'The Quant Green',
      sub: 'Our chances for every PGA Tour, DP World Tour, LIV and LPGA event, from 20,000 simulated tournaments built on ratings in strokes per round. Updated ' + fmt.ago(ix.updated_at) + '.' });
    var week = (ix.week || []).length ? '<div class="gr-week">' + ix.week.map(weekCard).join('') + '</div>'
      : QK.empty('No event this week', 'The next events appear here once their fields are set.');
    var recent = '<ul class="gr-list">' + (ix.recent || []).map(function (s) {
      var w = s.winner || {};
      return '<li><span>' + GR.eventLink(s.id, s.name) + '</span><span class="num">' + GR.toParHTML(w.tp) + '</span>' +
        '<small>' + esc(GR.tourShort(s.tour)) + ' · ' + esc(GR.dayMonth(s.end)) + ' · won by ' + esc(w.name || '—') +
        (isNum(w.win) ? ', our pre-event chance ' + GR.pct(w.win) : '') + '</small></li>';
    }).join('') + '</ul>';
    var stats = ev ? QK.stats([
      { label: 'Favourite won', value: GR.pct(ev.favourite_won), sub: 'of ' + ev.events + ' PGA Tour events, ' + ev.years[0] + '\u2013' + ev.years[1] + ' (sealed test)', tip: 'How often our pre-event favourite won. Golf is hard to call: even the best favourite usually loses.' },
      { label: 'Win skill', value: GR.pct(ev.win.skill), sub: 'better log loss than an even draw', signal: true },
      { label: 'Top-10 skill', value: GR.pct(ev.top10.skill), sub: 'than 10 in the field', signal: true },
      { label: 'Cut skill', value: GR.pct(ev.cut.skill), sub: 'than the field\u2019s cut rate', signal: true }
    ]) : '';
    el.innerHTML = head +
      '<section class="qk-section">' + QK.sectionHead({ title: 'This week', sub: 'Live events show chances from the scores so far; upcoming ones, our pre-event chances for the field as entered.' }) + week + '</section>' +
      '<section class="qk-section"><div class="qk-grid">' +
        '<div class="qk-span-4">' + GR.card('Men', 'Our rating: strokes a round better than an average PGA Tour player', topTable((ix.top || {}).men, '#/standings?s=men')) + '</div>' +
        '<div class="qk-span-4">' + GR.card('Women', 'Strokes a round better than an average LPGA Tour player', topTable((ix.top || {}).women, '#/standings?s=women')) + '</div>' +
        '<div class="qk-span-4">' + GR.card('Latest winners', 'The last 60 days, with what we gave them before the event', recent) + '</div>' +
      '</div></section>' +
      (stats ? '<section class="qk-section">' + QK.sectionHead({ title: 'How we\u2019re doing', sub: 'Scored once on seasons the model never saw while it was tuned.', actions: '<a class="qk-btn" href="#/model">How it works</a>', html: false }) + stats + '</section>' : '');
  });
});

// ── events (a tour's season) ───────────────────────────────────────────────

GR.page('events', function (el, params) {
  return GR.load('index.json').then(function (ix) {
    var tour = params.tour && GR.TOURS[params.tour] ? params.tour : 'pga';
    var seasons = ((ix.seasons || {})[tour] || []).slice().sort(function (a, b) { return b - a; });
    var season = params.season ? +params.season : seasons[0];
    return GR.load('schedule/' + tour + '/' + season + '.json').then(function (sc) {
      if (!el.isConnected) return;
      var ctl = '<div class="gr-controls">' + GR.seg('gr-tour', Object.keys(GR.TOURS).map(function (t) { return [t, GR.tourShort(t)]; }), tour, 'Tour') +
        '<label for="gr-season">Season</label><select id="gr-season" class="qk-select">' + seasons.map(function (s) { return '<option value="' + s + '"' + (s === season ? ' selected' : '') + '>' + s + '</option>'; }).join('') + '</select></div>';
      var evs = (sc.events || []).filter(function (e) { return !e.team || true; });
      var done = evs.filter(function (e) { return e.status === 'final' && e.winner; });
      var favWon = done.filter(function (e) { return e.fav && e.winner && e.fav.pid === e.winner.pid; }).length;
      el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: GR.tourName(tour), title: season + ' season',
          sub: evs.length + ' events' + (done.length ? '; our favourite won ' + favWon + ' of the ' + done.length + ' played' : '') + '.' }) + ctl + '<div id="gr-ev"></div>';
      QK.seg(el.querySelector('#gr-tour'), function (v) { location.hash = '#/fixtures/' + v; });
      el.querySelector('#gr-season').addEventListener('change', function (e) { location.hash = '#/fixtures/' + tour + '/' + e.target.value; });
      QK.table(el.querySelector('#gr-ev'), {
        dense: true, rows: evs.map(function (e) { var x = Object.assign({}, e); x.when = e.start; x.winner_name = e.winner ? e.winner.name : null; x.fav_win = e.fav ? e.fav.win : null; return x; }),
        rowHref: function (r) { return r.page ? '#/event/' + encodeURIComponent(r.id) : ''; },
        rowClass: function (r) { return r.status === 'live' ? 'gr-win' : ''; },
        columns: [
          { key: 'when', label: 'Dates', fmt: function (v, r) { return esc(GR.dates(r.start, r.end)); } },
          { key: 'name', label: 'Event', fmt: function (v, r) { return (r.page ? GR.eventLink(r.id, v) : esc(v)) + (r.major ? ' ' + QK.tag('Major') : '') + (r.team ? ' <span class="gr-muted">(team event)</span>' : '') + (r.status === 'live' ? ' ' + QK.tag('Live', 'live') : ''); } },
          { key: 'course', label: 'Course' },
          { key: 'purse', label: 'Purse', num: true, fmt: function (v) { return GR.money(v, true); } },
          { key: 'winner_name', label: 'Winner', fmt: function (v, r) { return r.winner ? GR.playerLink(r.winner.pid, r.winner.name) + ' ' + GR.toParHTML(r.winner.tp) : '<span class="gr-muted">' + (r.status === 'upcoming' ? 'to come' : '—') + '</span>'; } },
          { key: 'fav_win', label: 'Our favourite', num: true, tip: 'Our pre-event favourite and the chance we gave them to win', fmt: function (v, r) { return r.fav ? GR.playerLink(r.fav.pid, r.fav.name) + ' <span class="num">' + GR.pct(r.fav.win) + '</span>' : '—'; } }
        ]
      });
    });
  });
});

// ── rankings ───────────────────────────────────────────────────────────────

GR.page('rankings', function (el, params) {
  return GR.load('rankings.json').then(function (rk) {
    if (!el.isConnected) return;
    var s = params.query.s === 'women' ? 'women' : 'men';
    var rows = rk[s] || [];
    el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: 'Our rankings', title: s === 'men' ? 'Men' : 'Women',
        sub: (s === 'men' ? 'PGA Tour, DP World Tour and LIV players on one scale (they meet at the majors and co-sanctioned events). ' : 'LPGA Tour players. ') +
          'The rating is how many strokes a round better than an average ' + (s === 'men' ? 'PGA' : 'LPGA') + ' Tour player we expect each to score, from every round walked forward and weighted to the last nine months. Ranked: at least ' + rk.min_weight + ' recent rounds and a round in the last ' + rk.active_days + ' days.' }) +
      '<div class="gr-controls">' + GR.seg('gr-s', [['men', 'Men'], ['women', 'Women']], s, 'Rankings') + '</div><div id="gr-rk"></div>';
    QK.seg(el.querySelector('#gr-s'), function (v) { location.hash = '#/standings?s=' + v; });
    QK.table(el.querySelector('#gr-rk'), {
      dense: true, rows: rows, maxHeight: 900, rowHref: function (r) { return '#/player/' + encodeURIComponent(r.pid); },
      sort: { key: 'rank', dir: 'asc' },
      columns: [
        { key: 'rank', label: 'Rank', num: true, raw: true },
        { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return GR.playerLink(r.pid, v) + GR.thinTag(r.wt); } },
        { key: 'cc', label: 'Country' },
        { key: 'tour', label: 'Tour', fmt: function (v) { return esc(GR.tourShort(v)); } },
        { key: 'rt', label: 'Rating', num: true, ours: 'Ratings', tip: 'Strokes a round better than an average tour player', fmt: function (v) { return '<b>' + GR.rating(v) + '</b>'; } },
        { key: 'd90', label: '90 days', num: true, tip: 'Change in the rating over the last 90 days', fmt: function (v) { return isNum(v) ? '<span class="qk-delta ' + (v > 0.05 ? 'up' : v < -0.05 ? 'down' : 'flat') + '">' + fmt.signed(v, 2) + '</span>' : '—'; } },
        { key: 'wt', label: 'Rounds', num: true, tip: 'Recent rounds behind the rating (older rounds count for less: half after nine months)', fmt: function (v) { return fmt.num(v, 0); } },
        { key: 'starts', label: 'Starts', num: true, tip: 'Events in the last 12 months' },
        { key: 'wins', label: 'Wins', num: true },
        { key: 'top10', label: 'Top 10', num: true },
        { key: 'sg12', label: 'SG/round', num: true, tip: 'Strokes gained a round against the field, last 12 months', fmt: function (v) { return GR.rating(v); } },
        { key: 'earn', label: 'Earnings', num: true, tip: 'Official money in the last 12 months, where the tour publishes it', fmt: function (v) { return GR.money(v, true); } }
      ]
    });
  });
});

// ── players ────────────────────────────────────────────────────────────────

GR.page('players', function (el) {
  return Promise.all([GR.load('search.json'), GR.load('rankings.json')]).then(function (r) {
    if (!el.isConnected) return;
    var rank = {};
    ['men', 'women'].forEach(function (s) { (r[1][s] || []).forEach(function (x) { rank[x.pid] = x; }); });
    var all = (r[0].players || []).map(function (p) { var k = rank[p[0]]; return { pid: p[0], name: p[1], cc: p[2], rank: k ? k.rank : null, rt: k ? k.rt : null, tour: k ? k.tour : null }; });
    el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: 'Players', title: 'Every player',
        sub: all.length.toLocaleString('en-GB') + ' players with at least 20 scored rounds on the four tours. Ranked players show their rating; search by name or country.' }) +
      '<div class="gr-controls"><input id="gr-q" class="qk-input gr-search" type="search" placeholder="Search players" aria-label="Search players"></div><div id="gr-pl"></div>';
    var t = QK.table(el.querySelector('#gr-pl'), {
      dense: true, maxHeight: 900, rows: all, sort: { key: 'rt', dir: 'desc' }, rowHref: function (x) { return '#/player/' + encodeURIComponent(x.pid); },
      columns: [
        { key: 'name', label: 'Player', fmt: function (v, x) { return GR.playerLink(x.pid, v); } },
        { key: 'cc', label: 'Country' },
        { key: 'tour', label: 'Tour', fmt: function (v) { return v ? esc(GR.tourShort(v)) : '—'; } },
        { key: 'rank', label: 'Rank', num: true, raw: true },
        { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return GR.rating(v); } }
      ]
    });
    function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
    el.querySelector('#gr-q').addEventListener('input', function (e) {
      var q = norm(e.target.value).trim();
      t.setRows(q ? all.filter(function (x) { return norm(x.name).indexOf(q) >= 0 || norm(x.cc).indexOf(q) >= 0; }) : all);
    });
  });
});

// ── player ─────────────────────────────────────────────────────────────────

GR.page('player', function (el, params) {
  return GR.load('players/' + encodeURIComponent(params.id) + '.json').then(function (p) {
    if (!el.isConnected) return;
    var stream = p.stream === 'women' ? 'LPGA Tour' : 'PGA Tour';
    var sm = p.summary || {};
    var evs = p.events || [];
    var wins = evs.filter(function (e) { return e.st === 'finish' && e.pos === 1; }).length;
    var majors = evs.filter(function (e) { return e.major && e.st === 'finish' && e.pos === 1; }).length;
    var strip = [
      { label: 'Our rating', value: GR.rating(p.rt), sub: 'strokes a round v an average ' + stream + ' player', signal: true },
      { label: 'Rank', value: p.rank ? '#' + p.rank : '—', sub: p.ranked ? (p.stream === 'women' ? 'women' : 'men') : 'not ranked: too few recent rounds' },
      { label: 'Wins on file', value: String(wins), sub: majors ? majors + ' major' + (majors > 1 ? 's' : '') : 'events on file' },
      { label: 'Last 12 months', value: isNum(sm.starts) ? sm.starts + ' starts' : '—', sub: isNum(sm.top10) ? sm.top10 + ' top 10s, ' + GR.money(sm.earn, true) : '' }
    ];
    el.innerHTML = QK.playerHeader({ name: p.name, kicker: (p.stream === 'women' ? 'Women' : 'Men') + (sm.tour ? ' · ' + GR.tourName(sm.tour) : ''),
        meta: [p.cc ? ['Country', p.cc] : null, p.amateur ? 'Amateur' : null, ['Rounds on file', String(p.rounds)], p.last ? ['Last round', GR.dayMonth(p.last)] : null].filter(Boolean),
        strip: strip }) +
      (isNum(p.wt) && p.wt < GR.THIN ? QK.note('Thin record: only ' + Math.round(p.wt) + ' recent rounds sit behind this rating, so it can swing a long way on a few results.') : '') +
      '<section class="qk-section">' + GR.card('Rating over time', 'Before each event: strokes a round better than an average ' + stream + ' player at the time', '<div class="qk-chart" id="gr-h" style="height:300px"></div>') + '</section>' +
      '<section class="qk-section">' + GR.card('Season by season', 'Every event on file', '<div id="gr-s"></div>', { flush: true }) + '</section>' +
      '<section class="qk-section">' + GR.card('Events', 'Finish, strokes gained a round against the field, and the chances we gave before each event', '<div id="gr-e"></div>', { flush: true }) + '</section>';
    chartSafe(function () {
      QKC.line(el.querySelector('#gr-h'), { xType: 'time', series: [{ name: 'Rating', color: QKC.tokens().model, data: (p.history || []).map(function (h) { return [h[0], h[1]]; }), area: true }],
        yFmt: function (v) { return fmt.signed(v, 1); }, ref: { y: 0, label: 'tour average' }, label: 'Rating over time' });
    });
    QK.table(el.querySelector('#gr-s'), { dense: true, rows: p.seasons || [], sort: { key: 'season', dir: 'desc' }, columns: [
      { key: 'season', label: 'Season', raw: true }, { key: 'tour', label: 'Tour', fmt: function (v) { return esc(GR.tourShort(v)); } },
      { key: 'starts', label: 'Starts', num: true }, { key: 'cuts', label: 'Made cut', num: true }, { key: 'wins', label: 'Wins', num: true },
      { key: 'top10', label: 'Top 10', num: true }, { key: 'sg', label: 'SG/round', num: true, fmt: function (v) { return GR.rating(v); } },
      { key: 'earn', label: 'Earnings', num: true, fmt: function (v) { return GR.money(v, true); } }] });
    QK.table(el.querySelector('#gr-e'), { dense: true, maxHeight: 640, rows: evs, rowHref: function (e) { return '#/event/' + encodeURIComponent(e.id); }, sort: { key: 'date', dir: 'desc' },
      rowClass: function (e) { return e.st === 'finish' && e.pos === 1 ? 'gr-win' : e.st !== 'finish' ? 'gr-mc' : ''; },
      columns: [
        { key: 'date', label: 'Date', fmt: function (v) { return esc(v || '—'); } },
        { key: 'name', label: 'Event', fmt: function (v, e) { return GR.eventLink(e.id, v) + (e.major ? ' ' + QK.tag('Major') : ''); } },
        { key: 'tour', label: 'Tour', fmt: function (v) { return esc(GR.tourShort(v)); } },
        { key: 'pos', label: 'Finish', num: true, fmt: function (v, e) { return esc(GR.position(e)); } },
        { key: 'tp', label: 'To par', num: true, fmt: function (v) { return GR.toParHTML(v); } },
        { key: 'sg', label: 'SG/round', num: true, tip: 'Strokes gained a round against the field', fmt: function (v) { return GR.rating(v); } },
        { key: 'win', label: 'Our win', num: true, tip: 'Our chance to win, before the event', fmt: function (v) { return GR.pct(v); } },
        { key: 't10', label: 'Our top 10', num: true, fmt: function (v) { return GR.pct(v); } },
        { key: 'earn', label: 'Earnings', num: true, fmt: function (v) { return GR.money(v); } }] });
  });
});

// ── model ──────────────────────────────────────────────────────────────────

function calText(cal) {
  var w = (cal && cal.win) || [];
  if (!w.length) return '';
  var top = w[w.length - 1], big = w.slice().sort(function (a, b) { return b.n - a.n; })[0];
  var ratio = top.p > 0 ? top.freq / top.p : 1;
  var verdict = ratio > 1.2 ? 'Our strongest favourites win more often than we say, so the top of each field is undersold.'
    : ratio < 0.8 ? 'Our strongest favourites win less often than we say, so the top of each field is oversold.'
    : 'Our strongest favourites win about as often as we say.';
  return '<p>Players we gave ' + GR.pct(top.lo) + ' or more to win (' + GR.pct(top.p) + ' on average) won ' + GR.pct(top.freq) + ' of the time, across ' + fmt.num(top.n) + ' players. ' + verdict + '</p>' +
    '<p>The busiest bucket, ' + fmt.num(big.n) + ' players given ' + GR.pct(big.lo) + '\u2013' + GR.pct(big.hi) + ', won ' + GR.pct(big.freq) + ' against ' + GR.pct(big.p) + ' forecast.</p>';
}

function calBins(b) { return (b || []).map(function (x) { return { lo: x.lo, hi: x.hi, n: x.n, mean_p: x.p, freq: x.freq }; }); }

GR.page('model', function (el) {
  return GR.load('model.json').then(function (m) {
    if (!el.isConnected) return;
    var ev = m.events, rd = m.rounds;
    var stats = QK.stats([
      { label: 'Favourite won', value: GR.pct(ev.favourite_won), sub: ev.events + ' PGA Tour events, ' + ev.years[0] + '\u2013' + ev.years[1] },
      { label: 'Win skill', value: GR.pct(ev.win.skill), sub: 'log loss ' + ev.win.model + ' v ' + ev.win.base + ' for an even draw', signal: true },
      { label: 'Top-10 skill', value: GR.pct(ev.top10.skill), sub: 'log loss ' + ev.top10.model + ' v ' + ev.top10.base, signal: true },
      { label: 'Cut skill', value: GR.pct(ev.cut.skill), sub: ev.cut.events + ' events with a cut', signal: true },
      { label: 'Round correlation', value: fmt.num(rd.test.r, 3), sub: 'rating v strokes gained, ' + fmt.num(rd.test.n) + ' test rounds' }
    ]);
    var cov = Object.keys(m.coverage || {}).map(function (t) { var c = m.coverage[t]; var s = c.seasons || []; return { tour: c.name, from: s[0], to: s[s.length - 1], n: s.length, holes: c.holes ? 'yes' : 'no' }; });
    el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: 'The model', title: 'How it works and how we\u2019re doing' }) +
      '<section class="qk-section">' + stats + '</section>' +
      '<section class="qk-section gr-prose">' +
      '<h3>Ratings: strokes against the field</h3>' +
      '<p>Every round of every event is compared with the field that played it. A round\u2019s par for the field is the score an average player would have made that day: the mean of everyone\u2019s score plus the rating they brought in. Beating it by three strokes is three strokes gained, whether the course was easy or brutal and whatever the field\u2019s strength. The PGA Tour, the DP World Tour and LIV share one scale, tied together by the majors and the events they share; the LPGA is its own.</p>' +
      '<p>A player\u2019s rating is the weighted mean of their strokes gained, newer rounds counting for more: a round counts half after ' + Math.round(m.params.half_life) + ' days. It is pulled lightly towards a newcomer\u2019s level (worth ' + m.params.k0 + ' rounds), so a player with a short record can sit high on a few good weeks; those ratings are marked <i>thin record</i>. Ratings are shown against an average tour player of the last year.</p>' +
      '<h3>Chances: simulated tournaments</h3>' +
      '<p>Each player\u2019s round is their rating plus noise, a spread of ' + fmt.num(m.sd.men, 2) + ' strokes a round (men; ' + fmt.num(m.sd.women, 2) + ' women), rounded to whole strokes. We play the event ' + fmt.num(m.sims.now) + ' times with its real cut rule (the top 65 and ties after two rounds on most tours) and count how often each player wins, makes the top 5, 10 or 20, and makes the cut. A tie for first goes to a playoff between equals; top-10 finishes count ties. While an event is under way, the live chances start from each player\u2019s score and the holes they have left.</p>' +
      '<p>Every chance on an event page was made with nothing from that event or after it: the ratings are walked forward event by event.</p>' +
      '<h3>Chosen once, tested once</h3>' +
      '<p>The two settings (how fast old rounds fade and how hard to pull towards a newcomer\u2019s level) were chosen on PGA Tour rounds of ' + rd.train.years[0] + '\u2013' + rd.train.years[1] + ' by squared error, checked on ' + rd.valid.years[0] + '\u2013' + rd.valid.years[1] + ', and scored once on ' + rd.test.years[0] + '\u2013' + rd.test.years[1] + '. The table below is the grid.</p>' +
      '</section>' +
      '<section class="qk-section"><div class="qk-grid">' +
        '<div class="qk-span-6">' + GR.card('Win chances', 'Our pre-event chance to win against how often it happened, sealed test events', '<div class="qk-chart" id="gr-cw" style="height:320px"></div>') + '</div>' +
        '<div class="qk-span-6">' + GR.card('Top-10 chances', 'Our pre-event top-10 chance against how often it happened', '<div class="qk-chart" id="gr-ct" style="height:320px"></div>') + '</div>' +
        '<div class="qk-span-6">' + GR.card('Making the cut', 'Our pre-event chance to make the cut against how often it happened', '<div class="qk-chart" id="gr-cc" style="height:320px"></div>') + '</div>' +
        '<div class="qk-span-6">' + GR.card('What the test says', '', '<div class="gr-prose">' + calText(m.calibration) + '<p>A model change ships only when it beats this one on the sealed test seasons.</p></div>') + '</div>' +
      '</div></section>' +
      '<section class="qk-section"><div class="qk-grid">' +
        '<div class="qk-span-6">' + GR.card('Tuning grid', 'Mean squared error per round, lower is better; the chosen row first', '<div id="gr-g"></div>', { flush: true }) + '</div>' +
        '<div class="qk-span-6">' + GR.card('Coverage', 'Seasons on file (ESPN). Hole-by-hole scores on the PGA Tour (and the LPGA where ESPN has them)', '<div id="gr-cv"></div>', { flush: true }) + '</div>' +
      '</div></section>' +
      '<section class="qk-section gr-prose"><h3>Data</h3><p>Schedules, leaderboards, round and hole scores, courses and prize money come from ESPN\u2019s public golf scoreboards, used non-commercially and credited here. The PGA Tour\u2019s ShotLink data is licensed and is not used. Prediction-market prices for golf will appear beside our chances in a later update.</p></section>';
    chartSafe(function () { QKC.calibration(el.querySelector('#gr-cw'), { bins: calBins(m.calibration.win), subject: 'the player', unit: 'players', label: 'Win calibration' }); });
    chartSafe(function () { QKC.calibration(el.querySelector('#gr-ct'), { bins: calBins(m.calibration.top10), subject: 'the player', unit: 'players', label: 'Top-10 calibration' }); });
    chartSafe(function () { QKC.calibration(el.querySelector('#gr-cc'), { bins: calBins(m.calibration.cut), subject: 'the player', unit: 'players', label: 'Cut calibration' }); });
    QK.table(el.querySelector('#gr-g'), { dense: true, rows: m.grid || [], columns: [
      { key: 'half_life', label: 'Half-life (days)', num: true, raw: true }, { key: 'k0', label: 'Prior (rounds)', num: true, raw: true },
      { key: 'train', label: 'Train', num: true, fmt: function (v) { return fmt.num(v, 3); } }, { key: 'valid', label: 'Valid', num: true, fmt: function (v) { return fmt.num(v, 3); } }] });
    QK.table(el.querySelector('#gr-cv'), { dense: true, rows: cov, columns: [
      { key: 'tour', label: 'Tour' }, { key: 'from', label: 'From', raw: true }, { key: 'to', label: 'To', raw: true }, { key: 'n', label: 'Seasons', num: true }, { key: 'holes', label: 'Holes' }] });
  });
});

GR.page('disclaimer', function (el) {
  var t = document.getElementById('disclaimer-template');
  el.innerHTML = t ? t.innerHTML : '';
});
})();
