/* The Quant Green — the event page (#/event/<id>[/<tab>]): leaderboard, our forecast against the finish, holes, rounds. */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;
var TABS = [['board', 'Leaderboard'], ['forecast', 'Our forecast'], ['holes', 'Holes'], ['rounds', 'Rounds']];

function boardCols(e) {
  var live = !!e.live, up = e.status === 'upcoming';
  var cols = [];
  if (!up) cols.push({ key: 'order', label: 'Pos', num: true, raw: true, fmt: function (v, p) { return esc(GR.position(p)); } });
  cols.push({ key: 'name', label: 'Player', sticky: true, fmt: function (v, p) { return GR.playerLink(p.pid, v) + ' <span class="gr-muted">' + esc(p.cc || '') + '</span>' + GR.thinTag(p.wt); } });
  if (!up) {
    cols.push({ key: 'tp', label: 'To par', num: true, fmt: function (v) { return GR.toParHTML(v); } });
    for (var k = 0; k < e.rounds; k++) {
      (function (k) {
        cols.push({ key: 'r' + (k + 1), label: 'R' + (k + 1), num: true, fmt: function (v, p) {
          var s = p.r[k], th = p.thru[k];
          if (isNum(s)) return String(s);
          if (isNum(th) && th > 0) return GR.toParHTML(p.rtp[k]) + ' <span class="gr-muted">thru ' + th + '</span>';
          return '<span class="gr-muted">—</span>';
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
    '</div><section class="qk-section">' + GR.card('Every player', 'Our pre-event chances' + (fin ? ' beside the finish' : ''), '<div id="gr-ft"></div>', { flush: true }) + '</section>';
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
  QK.table(el.querySelector('#gr-ft'), { dense: true, maxHeight: 720, sort: { key: 'win', dir: 'desc' }, columns: cols,
    rows: pl.map(function (p) { var x = Object.assign({}, p); x.fin = p.st === 'finish' ? p.pos : 999; return x; }),
    rowClass: function (p) { return p.st === 'finish' && p.pos === 1 ? 'gr-win' : ''; } });
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
      diverging: true, fmt: function (v) { return fmt.signed(v, 2); }, catName: 'Hole', label: 'Scoring by hole' });
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
    QKC.bar(el.querySelector('#gr-rb'), { cats: ra.map(function (r) { return 'R' + r.round; }), series: [{ name: 'Against par', data: ra.map(function (r) { return r.avg_tp; }) }], diverging: true, labels: true, fmt: function (v) { return fmt.signed(v, 2); }, label: 'Field scoring by round' });
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
    var meta = [GR.dates(e.start, e.end), c.name ? c.name + (c.par ? ', par ' + c.par : '') + (c.yards ? ', ' + fmt.num(c.yards) + ' yards' : '') : null,
      e.purse ? GR.money(e.purse) + ' purse' : null, e.courses && e.courses.length > 1 ? e.courses.length + ' courses' : null].filter(Boolean);
    var stats = [
      { label: 'Field', value: String(e.players.length), sub: e.cut ? 'cut: top ' + e.cut.count + ' and ties after ' + e.cut.round + (isNum(e.cut.score) ? ', fell at ' + GR.toPar(e.cut.score) : '') : 'no cut' },
      winner ? { label: 'Winner', value: winner.name, text: true, sub: GR.toPar(winner.tp) + (e.playoff ? ' in a playoff' : '') + ', our pre-event chance ' + GR.pct(winner.win) } : null,
      leader ? { label: 'Live favourite', value: leader.name, text: true, sub: GR.pct(leader.lwin) + ' to win from ' + GR.toPar(leader.tp), signal: true } : null,
      fav ? { label: 'Our pre-event favourite', value: fav.name, text: true, sub: GR.pct(fav.win) + ' to win' + (fin ? ', finished ' + GR.position(fav) : ''), signal: !fin } : null
    ];
    var avail = TABS.filter(function (t) { return t[0] !== 'holes' || (e.holes || []).length; }).filter(function (t) { return e.status !== 'upcoming' || t[0] === 'forecast'; });
    if (!avail.some(function (t) { return t[0] === tab; })) tab = avail[0][0];
    el.innerHTML = QK.sectionHead({ tag: 'h1', size: 'lg', kicker: e.tour_name + ' · ' + e.season + (e.major ? ' · Major' : ''), title: e.name,
        sub: meta.join(' · '), actions: GR.statusTag(e.status), html: false }) +
      QK.stats(stats.filter(Boolean)) +
      (e.live ? QK.note('Live chances start from each player\u2019s score and the holes left, updated ' + fmt.ago(e.live.at) + '.') : '') +
      (avail.length > 1 ? '<div class="gr-controls" style="margin-top:var(--sp-4)">' + GR.seg('gr-tab', avail, tab, 'View') + '</div>' : '') +
      '<div id="gr-body"></div>';
    var body = el.querySelector('#gr-body');
    var seg = el.querySelector('#gr-tab');
    if (seg) QK.seg(seg, function (v) { location.replace('#/event/' + encodeURIComponent(e.id) + '/' + v); });
    if (tab === 'forecast') forecastTab(e, body);
    else if (tab === 'holes') holesTab(e, body);
    else if (tab === 'rounds') roundsTab(e, body);
    else QK.table(body, { dense: true, maxHeight: 900, columns: boardCols(e), rows: rowsOf(e), sort: e.live ? null : null,
      rowClass: function (p) { return p.st === 'finish' && p.pos === 1 ? 'gr-win' : (p.st === 'cut' || p.st === 'wd' || p.st === 'dq') ? 'gr-mc' : ''; } });
  });
});
})();
