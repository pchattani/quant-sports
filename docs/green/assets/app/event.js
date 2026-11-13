/* The Quant Green — the event page (#/event/<id>[/<tab>]): leaderboard, our forecast against the finish (and who beat
 * it), course fit (the field's history at the course before the event; what the course rewards), holes, rounds. */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;
var TABS = [['board', 'Leaderboard'], ['forecast', 'Our forecast'], ['course', 'Course fit'], ['holes', 'Holes'], ['rounds', 'Rounds']];

function boardCols(e) {
  var live = !!e.live, up = e.status === 'upcoming';
  var cols = [];
  if (!up) cols.push({ key: 'order', label: 'Pos', num: true, raw: true, fmt: function (v, p) { return esc(GR.position(p)); } });
  cols.push({ key: 'name', label: 'Player', sticky: true, fmt: function (v, p) { return GR.followStar(p.pid, v, e.stream) + GR.playerLink(p.pid, v) + ' <span class="gr-muted">' + esc(p.cc || '') + '</span>' + GR.thinTag(p.wt); } });
  if (!up) {
    cols.push({ key: 'tp', label: 'To par', num: true, fmt: function (v) { return GR.toParHTML(v); } });
    for (var k = 0; k < e.rounds; k++) {
      (function (k) {
        cols.push({ key: 'r' + (k + 1), label: 'R' + (k + 1), num: true, fmt: function (v, p) {
          var s = p.r[k], th = p.thru[k];
          if (isNum(s)) return String(s);
          if (isNum(th) && th > 0) return GR.toParHTML(p.rtp[k]) + ' <span class="gr-muted">thru ' + th + '</span>';
          /* some feeds carry only the round against par: show that rather than a blank */
          if (isNum((p.rtp || [])[k])) return GR.toParHTML(p.rtp[k]);
          return '';
        } });
      })(k);
    }
    cols.push({ key: 'tot', label: 'Total', num: true });
    cols.push({ key: 'sg', label: 'SG/round', num: true, tip: 'Strokes gained a round against the field at this event', fmt: function (v) { return GR.rating(v); } });
  }
  if (live) {
    cols.push({ key: 'lwin', label: 'Live win', num: true, ours: 'Live chance', fmt: function (v) { return '<b>' + GR.pct(v) + '</b>'; } });
    cols.push({ key: 'lt10', label: 'Live top 10', num: true, fmt: function (v) { return GR.pct(v); } });
  }
  cols.push({ key: 'win', label: up ? 'Win' : 'Pre-event win', num: true, ours: up ? 'Our chance' : undefined, tip: 'Our chance to win before the event started', fmt: function (v) { return up ? '<b>' + GR.pct(v) + '</b>' : GR.pct(v); } });
  cols.push({ key: 't10', label: up ? 'Top 10' : 'Pre-event top 10', num: true, fmt: function (v) { return GR.pct(v); } });
  if (up) {
    cols.push({ key: 't20', label: 'Top 20', num: true, fmt: function (v) { return GR.pct(v); } });
    if (e.cut) cols.push({ key: 'cut', label: 'Make cut', num: true, fmt: function (v) { return GR.pct(v); } });
    cols.push({ key: 'rt', label: 'Rating', num: true, tip: 'Strokes a round better than an average tour player, coming in', fmt: function (v) { return GR.rating(v); } });
  }
  if (e.status === 'final') cols.push({ key: 'earn', label: 'Earnings', num: true, fmt: function (v) { return GR.money(v); } });
  return cols;
}

function rowsOf(e) {
  return e.players.map(function (p, i) {
    var x = Object.assign({}, p);
    x.order = i + 1;
    for (var k = 0; k < e.rounds; k++) x['r' + (k + 1)] = p.r[k];
    return x;
  });
}

function forecastTab(e, el) {
  var pl = e.players.slice();
  var fin = e.status === 'final';
  var top = pl.slice().sort(function (a, b) { return (b.win || 0) - (a.win || 0); }).slice(0, 15);
  var rows = top.map(function (p) { return { label: p.name, p: p.win, href: '#/player/' + encodeURIComponent(p.pid), sub: fin ? 'finished ' + GR.position(p) : (isNum(p.rt) ? GR.rating(p.rt) : '') }; });
  var winner = fin ? pl.filter(function (p) { return p.pos === 1 && p.st === 'finish'; })[0] : null;
  var rankOfWinner = winner ? 1 + pl.filter(function (p) { return (p.win || 0) > (winner.win || 0); }).length : null;
  var note = winner ? QK.note('<b>' + esc(winner.name) + '</b> won. Before the event we gave them ' + GR.pct(winner.win) + ' to win, the ' + QK.ordinal(rankOfWinner) + ' best chance in the field, and expected them to finish about ' + QK.ordinal(Math.round(winner.xr || 0)) + '.') : '';
  el.innerHTML = note + '<div class="qk-grid">' +
    '<div class="qk-span-6">' + GR.card('Chance to win', 'Before the event, from ' + fmt.num(e.sims) + ' simulations', QK.chances(rows, { oursName: 'Our chance to win' })) + '</div>' +
    '<div class="qk-span-6">' + GR.card(fin ? 'Expected v actual finish' : 'Rating v chance', fin ? 'Each dot a player who made the cut: our expected finish before the event (across) and where they finished (up)' : 'Each dot a player: rating coming in and chance to finish in the top 10',
      '<div class="qk-chart" id="gr-sc" style="height:360px"></div>') + '</div>' +
    '</div>' + (fin ? beatList(pl) : '') + '<section class="qk-section">' + GR.card('Every player', 'Our pre-event chances' + (fin ? ' beside the finish' : ''), '<div id="gr-ft"></div>', { flush: true }) + '</section>';
  try {
    if (fin) {
      var pts = pl.filter(function (p) { return p.st === 'finish' && isNum(p.pos) && isNum(p.xr); }).map(function (p) { return { x: p.xr, y: p.pos, name: p.name, href: '#/player/' + encodeURIComponent(p.pid) }; });
      QKC.scatter(el.querySelector('#gr-sc'), { points: pts, xName: 'Expected finish', yName: 'Finish', yInverse: true, diagonal: true, label: 'Expected v actual finish' });
    } else {
      QKC.scatter(el.querySelector('#gr-sc'), { points: pl.filter(function (p) { return isNum(p.rt); }).map(function (p) { return { x: p.rt, y: (p.t10 || 0) * 100, name: p.name, href: '#/player/' + encodeURIComponent(p.pid) }; }),
        xName: 'Rating', yName: 'Top 10 (%)', label: 'Rating v top-10 chance' });
    }
  } catch (err) { if (window.console) console.error(err); }
  var cols = [
    { key: 'name', label: 'Player', sticky: true, fmt: function (v, p) { return GR.playerLink(p.pid, v) + GR.thinTag(p.wt); } },
    { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return GR.rating(v); } },
    { key: 'win', label: 'Win', num: true, ours: 'Our chance', fmt: function (v) { return '<b>' + GR.pct(v) + '</b>'; } },
    { key: 't5', label: 'Top 5', num: true, fmt: function (v) { return GR.pct(v); } },
    { key: 't10', label: 'Top 10', num: true, fmt: function (v) { return GR.pct(v); } },
    { key: 't20', label: 'Top 20', num: true, fmt: function (v) { return GR.pct(v); } }
  ];
  if (e.cut) cols.push({ key: 'cut', label: 'Make cut', num: true, fmt: function (v) { return GR.pct(v); } });
  cols.push({ key: 'xr', label: 'Expected finish', num: true, tip: 'Average finish across the simulations (a missed cut counts as last)', fmt: function (v) { return fmt.num(v, 0); } });
  if (fin) cols.push({ key: 'fin', label: 'Finish', num: true, fmt: function (v, p) { return esc(GR.position(p)); } });
  if (fin) cols.push({ key: 'beat', label: 'Beat forecast', num: true, tip: 'Places better than our expected finish (negative: worse)', fmt: function (v) { return isNum(v) ? GR.signed(v, 0) : ''; } });
  QK.table(el.querySelector('#gr-ft'), { dense: true, maxHeight: 720, sort: { key: 'win', dir: 'desc' }, columns: cols,
    rows: pl.map(function (p) { var x = Object.assign({}, p); x.fin = p.st === 'finish' ? p.pos : 999; return x; }),
    rowClass: function (p) { return p.st === 'finish' && p.pos === 1 ? 'gr-win' : ''; } });
}

/* who beat our forecast by the most places, and who fell furthest short (players who made the cut) */
function beatList(pl) {
  var f = pl.filter(function (p) { return isNum(p.beat); });
  if (f.length < 10) return '';
  var up = f.slice().sort(function (a, b) { return b.beat - a.beat; }).slice(0, 6);
  var dn = f.slice().sort(function (a, b) { return a.beat - b.beat; }).slice(0, 6);
  var li = function (p) { return '<li><span>' + GR.playerLink(p.pid, p.name) + ' <span class="gr-muted">expected ' + QK.ordinal(Math.round(p.xr)) + ', finished ' + esc(GR.position(p)) + '</span></span><b class="num">' + GR.signed(p.beat, 0) + '</b></li>'; };
  return '<section class="qk-section"><div class="qk-grid"><div class="qk-span-6">' + GR.card('Beat our forecast', 'Places better than the finish we expected before the event', '<ul class="gr-list">' + up.map(li).join('') + '</ul>') + '</div>' +
    '<div class="qk-span-6">' + GR.card('Fell short', 'Places worse than expected, among those who made the cut', '<ul class="gr-list">' + dn.map(li).join('') + '</ul>') + '</div></div></section>';
}

/* Course fit: the field's strokes gained at this course in earlier editions (no look-ahead: only rounds before the
   event), and what the course rewards. Course history is shown, not used: it failed the promotion test. */
function courseTab(e, el) {
  var withCh = e.players.filter(function (p) { return p.ch && isNum(p.ch.fit); });
  var html = '';
  if (withCh.length) {
    var rows = withCh.slice().sort(function (a, b) { return b.ch.fit - a.ch.fit; });
    html += (e.course_guess ? QK.note('The course is not announced in our feed until the event starts: this is the course of the last edition.') : '') + QK.note('Each player\u2019s strokes gained per round at this course in earlier editions, and how far that ran ahead of (or behind) their rating at the time, shrunk toward zero with 32 rounds of weight. <b>We show it but do not use it:</b> adding course history did not improve our forecasts on the sealed test seasons (the Model page has the numbers).') +
      '<div class="qk-grid"><div class="qk-span-6">' + GR.card('Plays this course best', 'Course fit: strokes a round better than their own rating here', '<ul class="gr-list">' + rows.slice(0, 10).map(function (p) {
        return '<li><span>' + GR.playerLink(p.pid, p.name) + ' <span class="gr-muted">' + p.ch.n + ' rounds, ' + p.ch.ev + (p.ch.ev === 1 ? ' edition' : ' editions') + '</span></span><b class="num">' + GR.signed(p.ch.fit, 2) + '</b></li>'; }).join('') + '</ul>') + '</div>' +
      '<div class="qk-span-6">' + GR.card('Course fit against our chance', 'Each dot a player with history here: fit across, our top-10 chance up', GR.chart('gr-cf', 340, 'Course fit against top-10 chance')) + '</div></div>' +
      '<section class="qk-section">' + GR.card('The field at this course', '', GR.table([{ label: 'Player', align: 'left' }, { label: 'Rounds' }, { label: 'Editions' }, { label: 'SG/round here' }, { label: 'Fit' }, { label: 'Our top 10' }],
        rows.map(function (p) { return [{ v: p.name, html: GR.playerLink(p.pid, p.name) }, { v: p.ch.n, html: String(p.ch.n) }, { v: p.ch.ev, html: String(p.ch.ev) }, { v: p.ch.sg, html: GR.signed(p.ch.sg, 2) }, { v: p.ch.fit, html: '<b>' + GR.signed(p.ch.fit, 2) + '</b>' }, { v: p.t10 || 0, html: GR.pct(p.t10) }]; }), { maxHeight: 560 }), { flush: true }) + '</section>';
  } else if (e.status !== 'final') {
    html += QK.note('None of this field has played this course in an edition on file' + (e.course_id ? '' : ' (or the event is played over more than one course, so rounds cannot be tied to a course)') + '.');
  }
  html += '<div id="gr-cinfo"></div>';
  el.innerHTML = html;
  if (withCh.length) GR.safe(function () {
    QKC.scatter(el.querySelector('#gr-cf'), { points: withCh.map(function (p) { return { x: p.ch.fit, y: (p.t10 || 0) * 100, name: p.name + ' · ' + p.ch.n + ' rounds here', label: GR.surname(p.name), href: GR.playerHref(p.pid) }; }),
      xName: 'Course fit (strokes a round against own rating)', yName: 'Our top-10 chance (%)', yFmt: function (v) { return Math.round(v) + '%'; }, labelTop: 8, label: 'Course fit against top-10 chance' });
  });
  if (!e.course_id) return;
  GR.maybe('courses/' + encodeURIComponent(e.course_id) + '.json').then(function (c) {
    var host = el.querySelector('#gr-cinfo');
    if (!host || !host.isConnected || !c) return;
    var rw = c.rw || {};
    var lab = { dist: 'Driving distance', acc: 'Driving accuracy', gir: 'Greens in regulation', ppg: 'Putting (fewer putts per green)', sand: 'Sand saves' };
    var keys = Object.keys(rw).filter(function (k) { return isNum(rw[k]); });
    var rwHtml = keys.length ? '<ul class="gr-list">' + keys.sort(function (a, b) { return Math.abs(rw[b]) - Math.abs(rw[a]); }).map(function (k) {
      var v = k === 'ppg' ? -rw[k] : rw[k];
      return '<li><span>' + esc(lab[k]) + '</span><b class="num">' + GR.signed(v, 2) + '</b></li>'; }).join('') + '</ul>' + GR.note('The correlation between each season statistic and how far players beat their own rating here (PGA Tour, 2017 on). Positive: the course rewards it.') : QK.empty('Not enough striking data at this course', 'What a course rewards needs PGA Tour rounds from 2017 on.');
    host.innerHTML = '<section class="qk-section"><div class="qk-grid"><div class="qk-span-6">' + GR.card(c.name, (c.par ? 'Par ' + c.par : '') + (c.yards ? ', ' + fmt.num(c.yards) + ' yards' : '') + ' · ' + c.events + ' editions on file, playing ' + GR.signed(c.diff, 2) + ' a round against par for an average field',
      '<p class="gr-meta"><a href="#/course/' + encodeURIComponent(c.id) + '">The course page: every edition, who plays it best, the hardest holes \u2192</a></p>' + (c.similar && c.similar.length ? '<p class="gr-meta">Courses most like it: ' + c.similar.map(function (x) { return GR.courseLink(x.id, x.name); }).join(', ') + '</p>' : '')) + '</div>' +
      '<div class="qk-span-6">' + GR.card('What it rewards', '', rwHtml) + '</div></div></section>';
  });
}

function holesTab(e, el) {
  var hs = e.holes || [];
  if (!hs.length) {
    el.innerHTML = QK.empty('No hole-by-hole scores', 'ESPN publishes hole scores for PGA Tour events on one course (and some LPGA events); this event has none on file.');
    return;
  }
  var hardest = hs.slice().sort(function (a, b) { return a.rank - b.rank; })[0];
  el.innerHTML = QK.note('Hardest hole: <b>the ' + QK.ordinal(hardest.h) + '</b> (par ' + hardest.par + (hardest.yd ? ', ' + hardest.yd + ' yards' : '') + '), playing ' + fmt.signed(hardest.avg, 2) + ' against par.') +
    '<div class="qk-grid"><div class="qk-span-12">' + GR.card('Scoring against par, hole by hole', 'Average strokes over par for every round played', '<div class="qk-chart" id="gr-hb" style="height:300px"></div>') + '</div></div>' +
    '<section class="qk-section">' + GR.card('Holes', '', '<div id="gr-ht"></div>', { flush: true }) + '</section>';
  try {
    QKC.bar(el.querySelector('#gr-hb'), { cats: hs.map(function (h) { return String(h.h); }), series: [{ name: 'Against par', data: hs.map(function (h) { return h.avg; }) }],
      diverging: true, fmt: function (v) { return fmt.signed(v, 2); }, catName: 'Hole', valName: 'Strokes against par', label: 'Scoring by hole' });
  } catch (err) { if (window.console) console.error(err); }
  QK.table(el.querySelector('#gr-ht'), { dense: true, rows: hs, columns: [
    { key: 'h', label: 'Hole', num: true, raw: true }, { key: 'par', label: 'Par', num: true }, { key: 'yd', label: 'Yards', num: true, raw: true },
    { key: 'avg', label: 'v par', num: true, fmt: function (v) { return fmt.signed(v, 2); } }, { key: 'rank', label: 'Difficulty', num: true, tip: '1 = hardest', raw: true },
    { key: 'eagle', label: 'Eagle+', num: true, fmt: function (v) { return GR.pct(v); } }, { key: 'birdie', label: 'Birdie', num: true, fmt: function (v) { return GR.pct(v); } },
    { key: 'par_', label: 'Par', num: true, fmt: function (v) { return GR.pct(v); } }, { key: 'bogey', label: 'Bogey', num: true, fmt: function (v) { return GR.pct(v); } },
    { key: 'double', label: 'Double+', num: true, fmt: function (v) { return GR.pct(v); } }] });
}

function roundsTab(e, el) {
  var ra = (e.round_avg || []).filter(function (r) { return r.n > 0; });
  if (!ra.length) { el.innerHTML = QK.empty('No rounds yet', 'Round scoring appears once a round is complete.'); return; }
  el.innerHTML = '<div class="qk-grid"><div class="qk-span-6">' + GR.card('Field scoring by round', 'Average score against par of the players who finished each round', '<div class="qk-chart" id="gr-rb" style="height:280px"></div>') + '</div>' +
    '<div class="qk-span-6">' + GR.card('Rounds', 'Field par: the score an average tour player would have made that day (our strokes-gained baseline)', '<div id="gr-rt"></div>', { flush: true }) + '</div></div>';
  try {
    QKC.bar(el.querySelector('#gr-rb'), { cats: ra.map(function (r) { return 'R' + r.round; }), series: [{ name: 'Against par', data: ra.map(function (r) { return r.avg_tp; }) }], diverging: true, labels: true, fmt: function (v) { return fmt.signed(v, 2); }, valName: 'Strokes against par', catName: 'Round', label: 'Field scoring by round' });
  } catch (err) { if (window.console) console.error(err); }
  QK.table(el.querySelector('#gr-rt'), { dense: true, rows: ra, columns: [
    { key: 'round', label: 'Round', num: true, raw: true }, { key: 'n', label: 'Players', num: true },
    { key: 'avg_tp', label: 'Average v par', num: true, fmt: function (v) { return fmt.signed(v, 2); } },
    { key: 'field_par', label: 'Field par', num: true, fmt: function (v) { return fmt.num(v, 2); } }] });
}

GR.page('event', function (el, params) {
  return GR.load('events/' + encodeURIComponent(params.id) + '.json').then(function (e) {
    if (!el.isConnected) return;
    var tab = params.tab || (e.status === 'upcoming' ? 'forecast' : 'board');
    var c = e.course || {};
    var fin = e.status === 'final';
    var winner = fin ? e.players.filter(function (p) { return p.pos === 1 && p.st === 'finish'; })[0] : null;
    var fav = e.players.filter(function (p) { return p.pid === e.fav; })[0];
    var leader = e.live ? e.players.slice().sort(function (a, b) { return (b.lwin || 0) - (a.lwin || 0); })[0] : null;
    var pl = e.players;
    /* where a player's pre-event chance ranked in the field (1 = our favourite) */
    var rankIn = function (p) { return 1 + pl.filter(function (q) { return (q.win || 0) > (p.win || 0); }).length; };
    var rated = pl.filter(function (p) { return isNum(p.rt); }).map(function (p) { return p.rt; }).sort(function (a, b) { return b - a; });
    var mean = function (a) { return a.length ? a.reduce(function (s, x) { return s + x; }, 0) / a.length : null; };
    var avgRt = mean(rated), top20 = rated.length >= 30 ? mean(rated.slice(0, 20)) : null;
    var thin = pl.filter(function (p) { return isNum(p.wt) && p.wt < GR.THIN; }).length;
    var beat = fin ? pl.filter(function (p) { return isNum(p.beat) && p.st === 'finish'; }).sort(function (a, b) { return b.beat - a.beat; })[0] : null;
    var scale = GR.scaleOf(e.stream);
    /* the cut line: "fell at" once it has been made, "projected at" while the event is live before it (ESPN's line) */
    var cutMade = pl.some(function (p) { return p.st === 'cut'; });
    var cutTxt = e.cut ? 'cut: top ' + e.cut.count + ' and ties after round ' + e.cut.round + (isNum(e.cut.score) && (cutMade || e.live) ? (cutMade ? ', fell at ' : ', projected at ') + GR.toPar(e.cut.score) : '') : 'no cut';
    /* the black strip: the field, how strong it was, the winner (or the live leader) against our pre-event chance, our
       favourite and how they did, and who beat our forecast by most. Every chance is the one we published before the start. */
    var strip = [
      { label: 'Field', value: String(pl.length), unit: 'players', sub: cutTxt },
      isNum(avgRt) ? { label: 'Field strength', value: GR.signed(avgRt, 2), sub: 'the average rating coming in, strokes a round v ' + scale + (isNum(top20) ? '; the top 20 average ' + GR.signed(top20, 2) : ''),
        tip: 'Each player’s rating before the event (rounds played before it only), averaged over the field' } : null,
      winner ? { label: 'Winner', value: winner.name, text: true, href: GR.playerHref(winner.pid), sub: GR.toPar(winner.tp) + (e.playoff ? ' in a playoff' : '') + ' · our pre-event chance ' + GR.pct(winner.win) + ', ' + GR.nthBest(rankIn(winner)) + ' in the field' } : null,
      leader ? { label: 'Live favourite', value: leader.name, text: true, href: GR.playerHref(leader.pid), signal: true, sub: GR.pct(leader.lwin) + ' to win now, from ' + (GR.toPar(leader.tp) || 'level') + ' (' + GR.pct(leader.win) + ' before the start)' } : null,
      fav ? { label: fin ? 'Our favourite' : 'Our pre-event favourite', value: fav.name, text: true, href: GR.playerHref(fav.pid), signal: !fin && !leader,
        sub: GR.pct(fav.win) + ' to win before the start' + (fin ? ' · finished ' + (GR.position(fav) || 'out') + (isNum(fav.xr) ? ' (expected ' + QK.ordinal(Math.round(fav.xr)) + ')' : '') : (e.status === 'live' && GR.position(fav) ? ' · ' + GR.position(fav) + ' now' : '')) } : null,
      beat && beat.beat >= 1 ? { label: 'Beat our forecast most', value: beat.name, text: true, href: GR.playerHref(beat.pid), sub: GR.signed(beat.beat, 0) + ' places: expected ' + QK.ordinal(Math.round(beat.xr)) + ', finished ' + GR.position(beat) } : null
    ].filter(Boolean);
    /* How sure are we? what the favourite's chance means, the winner against it, and the sample behind every chance */
    var sure = '';
    if (leader) sure = 'Live chances start from each player’s score and the holes left, ' + esc(GR.asOf(e.live.at)) + '. ' + esc(leader.name) + '’s ' + GR.pct(leader.lwin) + ' comes off ' + GR.oneIn(leader.lwin) + '. ';
    if (fav) sure += (fin ? 'Our favourite, ' + esc(fav.name) + ', had ' : 'Our pre-event favourite, ' + esc(fav.name) + ', ' + (e.status === 'live' ? 'had ' : 'has ')) + GR.pct(fav.win) + ': a chance like that comes off ' + GR.oneIn(fav.win) + ', so in golf even the favourite usually loses. ';
    if (winner) { var wr = rankIn(winner); sure += esc(winner.name) + ' won from ' + GR.pct(winner.win) + ', ' + GR.nthBest(wr) + ' chance in the field' + (wr === 1 ? ': our favourite came through. ' : wr <= 3 ? '. ' : wr <= 10 ? ': near the top of our list. ' : winner.win < 0.01 ? ': a long shot. ' : ': outside our top ten. '); }
    sure += 'Every chance comes from ' + fmt.num(e.sims) + ' simulated tournaments, with ratings built only from rounds played before the event' + (thin ? '; ' + thin + ' of the ' + pl.length + ' players had fewer than ' + GR.THIN + ' recent rounds behind their rating, so their chances are rougher.' : '.');
    var chips = [GR.dates(e.start, e.end),
      c.name ? (e.course_id ? '<a href="#/course/' + encodeURIComponent(e.course_id) + '">' + esc(c.name) + '</a>' : c.name) : null,
      c.par ? ['Par', String(c.par)] : null, c.yards ? fmt.num(c.yards) + ' yards' : null,
      e.purse ? GR.money(e.purse, true) + ' purse' : null, e.courses && e.courses.length > 1 ? e.courses.length + ' courses' : null];
    var avail = TABS.filter(function (t) { return t[0] !== 'holes' || (e.holes || []).length; })
      .filter(function (t) { return t[0] !== 'course' || e.course_id || e.players.some(function (p) { return p.ch; }); })
      .filter(function (t) { return e.status !== 'upcoming' || t[0] === 'forecast' || t[0] === 'course'; });
    if (!avail.some(function (t) { return t[0] === tab; })) tab = avail[0][0];
    el.innerHTML = '<nav class="gr-crumb"><a href="#/fixtures/' + e.tour + '/' + e.season + '">' + esc(e.season + ' ' + e.tour_name) + '</a> / ' + esc(e.name) + '</nav>' +
      QK.playerHeader({ name: GR.shortEvent(e.name), face: String(e.season), kicker: [e.tour_name, e.major ? 'Major' : 'Tour event', String(e.season)].join(' · '),
        team: { name: e.tour_name, abbr: GR.tourShort(e.tour), colour: GR.TOUR_COL[e.tour], href: '#/fixtures/' + e.tour + '/' + e.season },
        meta: chips, tags: [GR.statusTag(e.status)].filter(Boolean), strip: strip, short: { title: 'How sure are we?', html: sure } }) +
      '<p class="gr-meta gr-asof">Every number on this page comes from the event file, ' + esc(GR.asOf(e.updated_at)) + '.' + (e.course_id ? ' ' + GR.courseLink(e.course_id, 'The course page: every edition, who plays it best →') : '') + '</p>' +
      (avail.length > 1 ? '<div class="gr-controls" style="margin-top:var(--sp-4)">' + GR.seg('gr-tab', avail, tab, 'View') + '</div>' : '') +
      '<div id="gr-body"></div>';
    document.title = e.name + ' ' + e.season + ' · The Quant Green';
    var body = el.querySelector('#gr-body');
    var seg = el.querySelector('#gr-tab');
    if (seg) QK.seg(seg, function (v) { location.replace('#/event/' + encodeURIComponent(e.id) + '/' + v); });
    if (tab === 'forecast') forecastTab(e, body);
    else if (tab === 'holes') holesTab(e, body);
    else if (tab === 'course') courseTab(e, body);
    else if (tab === 'rounds') roundsTab(e, body);
    else QK.table(body, { dense: true, maxHeight: 900, columns: boardCols(e), rows: rowsOf(e), sort: e.live ? null : null,
      rowClass: function (p) { return p.st === 'finish' && p.pos === 1 ? 'gr-win' : (p.st === 'cut' || p.st === 'wd' || p.st === 'dq') ? 'gr-mc' : ''; } });
  });
});
})();
